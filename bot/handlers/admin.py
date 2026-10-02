from __future__ import annotations

import logging
from datetime import date, datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings, settings_for_club
from bot.db.enums import AuditAction
from bot.db.models import Challenge, Club, DailyCode, Participation, User
from bot.filters import IsAdmin
from bot.keyboards.participant import WIPE_NO_CB, WIPE_YES_CB, wipe_keyboard
from bot.repositories import audit as audit_repo
from bot.repositories import clubs as clubs_repo
from bot.repositories import submissions as submissions_repo
from bot.repositories import users as users_repo
from bot.services import backup as backup_service
from bot.services import challenge as challenge_service
from bot.services import daily_code as daily_code_service
from bot.services import day_close as day_close_service
from bot.services import announce as announce_service
from bot.services import export as export_service
from bot.services import notifications as notifications_service
from bot.services import stats as stats_service
from bot.services.challenge_day import current_day_number
from bot.utils.text_format import dropoff_chart
from bot.utils.timeutil import now_utc

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(IsAdmin())

# Служебное сообщение о миграции чата приходит не от админа, поэтому
# фильтр IsAdmin на нём неприменим — нужен отдельный роутер.
migration_router = Router(name="chat_migration")


def _parse_date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


@router.message(Command("chatid"))
async def cmd_chatid(message: Message) -> None:
    """В форуме мало id чата: у каждого топика свой message_thread_id,
    и без него бот не поймёт, в какую ветку писать."""
    lines = [f"chat_id: <code>{message.chat.id}</code>"]
    if message.message_thread_id:
        lines.append(f"thread_id: <code>{message.message_thread_id}</code>")
        lines.append(f"<i>топик: {texts.esc(message.reply_to_message.forum_topic_created.name)}</i>"
                     if message.reply_to_message
                     and message.reply_to_message.forum_topic_created
                     else "<i>это топик форума</i>")
    elif message.chat.is_forum:
        lines.append("<i>это общая ветка форума, не топик</i>")
    await message.answer("\n".join(lines))


@router.message(F.chat.type == "private", F.forward_origin, ~F.video_note)
async def cmd_forwarded_chatid(message: Message) -> None:
    """Узнать id канала: переслать боту любой пост оттуда. В самом канале
    /chatid не сработает — у постов канала нет отправителя-пользователя."""
    chat = getattr(message.forward_origin, "chat", None)
    if chat is None:
        return
    await message.answer(
        f"Переслано из «{texts.esc(chat.title or chat.id)}»\n"
        f"chat_id: <code>{chat.id}</code>"
    )


@migration_router.message(F.migrate_to_chat_id)
async def on_chat_migrated(message: Message, bot: Bot, settings: Settings) -> None:
    """При апгрейде группы в супергруппу Telegram меняет chat_id, и бот молча
    перестаёт принимать кружки. Кричим админам, пока никто не потерял день."""
    new_id = message.migrate_to_chat_id
    old_id = message.chat.id
    logger.warning("Чат %s мигрировал в %s — нужно обновить .env", old_id, new_id)

    which = "PARTICIPANTS_CHAT_ID" if old_id == settings.participants_chat_id else "JUDGES_CHAT_ID"
    for admin_id in settings.admin_ids:
        await notifications_service.notify(
            bot, admin_id, texts.chat_migrated(which, old_id, new_id)
        )


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message, session: AsyncSession, settings: Settings) -> None:
    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        await message.answer(texts.GENERIC_ERROR)
        return

    day = current_day_number(
        now_utc(), challenge.start_date, settings.tz, settings.day_boundary_hour
    )
    data = await stats_service.build_dashboard(session, challenge.id, day)
    await message.answer(
        texts.dashboard(
            challenge_title=challenge.title,
            is_test=challenge.is_test,
            day=day,
            active=data.active,
            submitted_today=data.submitted_today,
            approved_today=data.approved_today,
            avg_percent=data.avg_percent,
            dropoff=dropoff_chart(data.dropoff),
        )
    )


@router.message(Command("export"))
async def cmd_export(
    message: Message, session: AsyncSession, user: User, settings: Settings
) -> None:
    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        await message.answer(texts.GENERIC_ERROR)
        return

    payload = await export_service.build_xlsx(session, challenge.id, settings.tz)
    if payload is None:
        await message.answer(texts.EXPORT_EMPTY)
        return

    stamp = now_utc().astimezone(settings.tz).strftime("%Y-%m-%d")
    await message.answer_document(
        BufferedInputFile(payload, filename=f"challenge-{stamp}.xlsx"),
        caption=texts.EXPORT_CAPTION.format(date=stamp),
    )
    await audit_repo.log(
        session, actor_id=user.telegram_id, action=AuditAction.EXPORT, target_type="challenge",
        target_id=challenge.id,
    )


@router.message(Command("set_code"))
async def cmd_set_code(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer(texts.SET_CODE_USAGE)
        return

    day = _parse_date(parts[0])
    if day is None:
        await message.answer(texts.SET_CODE_USAGE)
        return

    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        await message.answer(texts.GENERIC_ERROR)
        return

    code = await daily_code_service.set_manual_code(session, challenge, day, parts[1])
    await audit_repo.log(
        session,
        actor_id=user.telegram_id,
        action=AuditAction.SET_CODE,
        target_type="daily_code",
        payload={"date": day.isoformat(), "code": code},
    )
    await message.answer(texts.SET_CODE_OK.format(date=day.isoformat(), code=texts.esc(code)))


@router.message(Command("simulate_day"))
async def cmd_simulate_day(
    message: Message,
    command: CommandObject,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    if not settings.test_mode:
        await message.answer(texts.SIMULATE_ONLY_TEST)
        return

    day = _parse_date(command.args or "")
    if day is None:
        await message.answer(texts.SIMULATE_USAGE)
        return

    report = await day_close_service.close_day(session, settings, day)
    if report is None:
        await message.answer(texts.GENERIC_ERROR)
        return

    await audit_repo.log(
        session,
        actor_id=user.telegram_id,
        action=AuditAction.SIMULATE_DAY,
        payload={"date": day.isoformat()},
    )
    await message.answer(
        texts.SIMULATE_OK.format(date=day.isoformat(), day=report.day, missed=len(report.missed))
    )


@router.message(Command("wipe_test"))
async def cmd_wipe_test(message: Message, settings: Settings) -> None:
    if not settings.test_mode:
        await message.answer(texts.WIPE_ONLY_TEST)
        return
    await message.answer(texts.WIPE_CONFIRM, reply_markup=wipe_keyboard())


@router.callback_query(F.data == WIPE_YES_CB, IsAdmin())
async def cb_wipe_yes(
    callback: CallbackQuery, session: AsyncSession, user: User, settings: Settings
) -> None:
    if not settings.test_mode:
        await callback.answer(texts.WIPE_ONLY_TEST, show_alert=True)
        return

    submissions_deleted = await submissions_repo.delete_for_test_challenges(session)
    test_challenge_ids = list(
        await session.scalars(select(Challenge.id).where(Challenge.is_test.is_(True)))
    )
    participations_deleted = 0
    if test_challenge_ids:
        result = await session.execute(
            delete(Participation).where(Participation.challenge_id.in_(test_challenge_ids))
        )
        participations_deleted = int(result.rowcount or 0)
        await session.execute(
            delete(DailyCode).where(DailyCode.challenge_id.in_(test_challenge_ids))
        )

    await audit_repo.log(
        session,
        actor_id=user.telegram_id,
        action=AuditAction.WIPE_TEST,
        payload={"submissions": submissions_deleted, "participations": participations_deleted},
    )
    await callback.answer()
    await callback.message.edit_text(
        texts.WIPE_DONE.format(
            submissions=submissions_deleted, participations=participations_deleted
        )
    )


@router.callback_query(F.data == WIPE_NO_CB, IsAdmin())
async def cb_wipe_no(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(texts.WIPE_CANCELLED)


@router.message(Command("ban"))
async def cmd_ban(
    message: Message, command: CommandObject, session: AsyncSession, user: User
) -> None:
    parts = (command.args or "").split(maxsplit=1)
    if not parts or not parts[0].lstrip("-").isdigit():
        await message.answer(texts.BAN_USAGE)
        return

    target = int(parts[0])
    reason = parts[1] if len(parts) > 1 else None
    if not await users_repo.set_blocked(session, target, True, reason):
        await message.answer(texts.USER_NOT_FOUND)
        return

    await audit_repo.log(
        session,
        actor_id=user.telegram_id,
        action=AuditAction.BAN,
        target_type="user",
        target_id=target,
        payload={"reason": reason},
    )
    await message.answer(texts.BAN_OK.format(id=target))


@router.message(Command("unban"))
async def cmd_unban(
    message: Message, command: CommandObject, session: AsyncSession, user: User
) -> None:
    raw = (command.args or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(texts.UNBAN_USAGE)
        return

    target = int(raw)
    if not await users_repo.set_blocked(session, target, False):
        await message.answer(texts.USER_NOT_FOUND)
        return

    await audit_repo.log(
        session,
        actor_id=user.telegram_id,
        action=AuditAction.UNBAN,
        target_type="user",
        target_id=target,
    )
    await message.answer(texts.UNBAN_OK.format(id=target))


@router.message(Command("broadcast"))
async def cmd_broadcast(
    message: Message,
    command: CommandObject,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    text = (command.args or "").strip()
    if not text:
        await message.answer(texts.BROADCAST_USAGE)
        return

    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        await message.answer(texts.GENERIC_ERROR)
        return

    await audit_repo.log(
        session,
        actor_id=user.telegram_id,
        action=AuditAction.BROADCAST,
        payload={"text": text[:200]},
    )
    await session.commit()

    # Рассылки в личку нет: бот не может написать первым тому, кто не
    # нажимал /start, — зато в беседе есть все.
    await announce_service.post_to_chat(bot, settings, text)
    await message.answer(texts.BROADCAST_DONE)


@router.message(Command("backup"))
async def cmd_backup(message: Message, settings: Settings) -> None:
    path = await backup_service.make_backup(settings.backup_dir, settings.tz, settings.backup_keep)
    size = backup_service.size_mb(path)
    if size > backup_service.MAX_UPLOAD_MB:
        await message.answer(
            texts.BACKUP_TOO_BIG.format(name=path.name, size=round(size, 1), path=path.parent)
        )
        return
    await message.answer_document(
        FSInputFile(path),
        caption=texts.BACKUP_CAPTION.format(
            date=now_utc().astimezone(settings.tz).strftime("%d.%m.%Y %H:%M")
        ),
    )


@router.message(Command("newclub"))
async def cmd_newclub(
    message: Message, session: AsyncSession, user: User, settings: Settings
) -> None:
    """Заводит клуб на текущей группе. Запускать в том топике, куда будут
    присылать кружки: он и станет топиком челленджа.

    Пока группа не заведена, бот в ней молчит — так добавление в чужой чат
    ничего не ломает.
    """
    if message.chat.type == "private":
        await message.answer(texts.NEWCLUB_IN_GROUP)
        return

    existing = await clubs_repo.get_by_chat(session, message.chat.id)
    if existing is not None:
        await message.answer(texts.club_already(existing.title))
        return

    club = await clubs_repo.create(
        session,
        title=message.chat.title or "Клуб",
        chat_id=message.chat.id,
        participants_thread_id=message.message_thread_id or 0,
        judges_chat_id=settings.judges_chat_id,
        judge_ids=[user.telegram_id],
        admin_ids=[user.telegram_id],
    )
    await session.commit()

    # Без челленджа клуб мёртвый: /start ответит ошибкой, вступать некуда.
    # Заводим сразу, на настройках из .env — правится потом.
    challenge = await challenge_service.ensure_current(
        session, settings_for_club(settings, club), club
    )
    await session.commit()
    await message.answer(
        texts.club_created(club.title, message.message_thread_id, challenge.start_date)
    )


@router.message(Command("clubs"))
async def cmd_clubs(message: Message, session: AsyncSession) -> None:
    clubs = await clubs_repo.list_active(session)
    if not clubs:
        await message.answer(texts.CLUBS_EMPTY)
        return
    await message.answer(
        texts.clubs_list(
            [
                (c.title, c.chat_id, c.participants_thread_id, len(c.judge_ids or []))
                for c in clubs
            ]
        )
    )


@router.message(Command("setclub"))
async def cmd_setclub(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    club: Club | None,
    settings: Settings,
) -> None:
    """Настройка клуба: задание, призы, название и топики.

    Топики задаются без аргументов — прямо из нужной ветки: так не надо
    вручную переписывать thread_id, который всё равно берётся из сообщения.
    """
    if club is None:
        await message.answer(texts.SETCLUB_NO_CLUB)
        return

    raw = (command.args or "").strip()
    if not raw:
        await message.answer(texts.setclub_help(club.title, club.challenge_task, club.prizes))
        return

    field, _, value = raw.partition(" ")
    field = field.lower()
    value = value.strip()
    thread = message.message_thread_id or 0

    if field in {"task", "задание"}:
        if not value:
            await message.answer(texts.SETCLUB_NEED_VALUE)
            return
        club.challenge_task = value
    elif field in {"prizes", "призы"}:
        club.prizes = value  # пустое значение = убрать блок призов
    elif field in {"name", "название"}:
        if not value:
            await message.answer(texts.SETCLUB_NEED_VALUE)
            return
        club.title = value
    elif field in {"circles", "кружки"}:
        club.chat_id, club.participants_thread_id = message.chat.id, thread
    elif field in {"trainings", "тренировки"}:
        club.trainings_thread_id = thread
    elif field in {"checkins", "приходы"}:
        club.checkins_thread_id = thread
    elif field in {"judges", "судьи"}:
        club.judges_chat_id = message.chat.id
    elif field in {"challenge", "челлендж"}:
        flag = value.lower()
        if flag not in {"on", "off", "вкл", "выкл"}:
            await message.answer(texts.SETCLUB_CHALLENGE_USAGE)
            return
        club.challenge_enabled = flag in {"on", "вкл"}
    else:
        await message.answer(texts.setclub_help(club.title, club.challenge_task, club.prizes))
        return

    await audit_repo.log(
        session, actor_id=message.from_user.id, action=AuditAction.TRAINING_UPDATED,
        target_type="club", target_id=club.id, payload={"field": field},
    )
    await session.commit()
    await message.answer(
        texts.setclub_done(field, thread, message.chat.id, club.challenge_enabled)
    )
