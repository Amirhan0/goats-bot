from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.enums import ParticipationStatus
from bot.db.models import User
from bot.filters import InParticipantsChat
from bot.keyboards.participant import JOIN_CB, join_keyboard, leave_keyboard, parse_leave_cb
from bot.repositories import participations as participations_repo
from bot.services import challenge as challenge_service
from bot.services import daily_code as daily_code_service
from bot.services import participation as participation_service
from bot.services.challenge_day import current_day_number, local_day_for
from bot.utils.timeutil import format_date_ru, now_utc

router = Router(name="start")


def _launch_date(settings: Settings) -> str | None:
    """До боевого запуска показываем, когда он будет. После — молчим."""
    if not settings.test_mode:
        return None
    return format_date_ru(settings.challenge_start_date)


@router.message(CommandStart())
async def cmd_start(
    message: Message, session: AsyncSession, user: User, settings: Settings
) -> None:
    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        await message.answer(texts.GENERIC_ERROR)
        return

    # Бот делает уже не только челлендж, поэтому в личке — общий вход,
    # а правила с кнопкой «Участвовать» живут в беседе, где они и нужны.
    if message.chat.type == "private":
        await message.answer(
            texts.hub_text(
                settings.club_name,
                is_judge=settings.is_judge(user.telegram_id),
                is_admin=settings.is_admin(user.telegram_id),
                trainings_on=settings.trainings_enabled,
                launch=_launch_date(settings),
            )
        )
        return

    # Бот сидит и в других группах клуба. Вступать в челлендж можно только
    # из его беседы: иначе человек нажмёт «Участвовать» где-нибудь ещё, кружки
    # оттуда приниматься не будут (фильтр по топику), и он навсегда поселится
    # в ночном списке «Пропустили».
    if not settings.in_participants_thread(message.chat.id, message.message_thread_id):
        return

    existing = await participations_repo.get(session, user.id, challenge.id)
    day = current_day_number(
        now_utc(), challenge.start_date, settings.tz, settings.day_boundary_hour
    )
    if existing is not None and existing.status == ParticipationStatus.ACTIVE:
        await message.reply(texts.already_joined(max(day, 0)))
        return

    await message.answer(
        texts.start_greeting(
            challenge.title,
            challenge_service.rules_of(challenge, settings),
            # Именно боевая дата из конфига: у тестового челленджа старт —
            # сегодняшний день, и показывать его как «стартуем» бессмысленно.
            format_date_ru(settings.challenge_start_date),
            challenge.is_test,
        ),
        reply_markup=join_keyboard(),
    )


@router.callback_query(F.data == JOIN_CB)
async def cb_join(
    callback: CallbackQuery, session: AsyncSession, user: User, settings: Settings
) -> None:
    """Кнопку нажимает каждый за себя — одно сообщение с кнопкой в беседе
    обслуживает всех сразу."""
    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        await callback.answer(texts.GENERIC_ERROR, show_alert=True)
        return

    # Та же защита, что и в /start: кнопка могла уехать пересылкой в другую
    # группу, а вступление оттуда оставляет человека вечным «пропустившим».
    chat = callback.message.chat if callback.message else None
    thread = getattr(callback.message, "message_thread_id", None)
    if chat is not None and chat.type != "private":
        if not settings.in_participants_thread(chat.id, thread):
            await callback.answer(texts.WRONG_CHAT, show_alert=True)
            return

    result = await participation_service.join(session, settings, user, challenge)
    if not result.created:
        await callback.answer(texts.already_joined(max(result.day, 0)), show_alert=True)
        return

    if result.day < 1:
        await callback.answer(
            texts.CHALLENGE_NOT_STARTED.format(date=challenge.start_date.strftime("%d.%m.%Y")),
            show_alert=True,
        )
        return

    # Слово дня выдаём сразу и во всплывашке: иначе вступивший днём узнает его
    # только завтра в 09:00, а сдавать ему уже сегодня.
    day_date = local_day_for(now_utc(), settings.tz, settings.day_boundary_hour)
    code = await daily_code_service.ensure_code(session, challenge, day_date, settings)
    await callback.answer(texts.joined_popup(result.day, code), show_alert=True)

    if callback.message is not None:
        await callback.message.answer(
            texts.joined_chat(user.mention_html, result.day)
        )


@router.message(F.new_chat_members, InParticipantsChat())
async def on_new_members(
    message: Message, bot: Bot, session: AsyncSession, settings: Settings
) -> None:
    """Новому человеку иначе никто не объяснит, что тут происходит."""
    me = await bot.me()
    newcomers = [u for u in (message.new_chat_members or []) if not u.is_bot]
    if not newcomers or me.id in {u.id for u in (message.new_chat_members or [])}:
        return

    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        return

    names = ", ".join(
        f'<a href="tg://user?id={u.id}">{texts.esc(u.first_name)}</a>' for u in newcomers
    )
    greeting = texts.welcome(names, challenge_service.rules_of(challenge, settings))
    launch = _launch_date(settings)
    await message.answer(
        f"{greeting}\n\n{texts.launch_notice(launch)}" if launch else greeting,
        reply_markup=join_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message, user: User, settings: Settings) -> None:
    await message.reply(
        texts.help_text(
            settings.challenge_task,
            is_judge=settings.is_judge(user.telegram_id),
            is_admin=settings.is_admin(user.telegram_id),
            daily_code=settings.daily_code_enabled,
        )
    )


@router.message(Command("rules"))
async def cmd_rules(message: Message, session: AsyncSession, settings: Settings) -> None:
    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        await message.reply(texts.GENERIC_ERROR)
        return
    await message.reply(challenge_service.rules_of(challenge, settings))


@router.message(Command("prizes"))
async def cmd_prizes(message: Message, settings: Settings) -> None:
    await message.reply(settings.prizes or texts.NO_PRIZES)


@router.message(Command("leave"))
async def cmd_leave(
    message: Message, session: AsyncSession, user: User, settings: Settings
) -> None:
    challenge = await challenge_service.get_current(session, settings)
    participation = (
        await participations_repo.get(session, user.id, challenge.id) if challenge else None
    )
    if participation is None or participation.status != ParticipationStatus.ACTIVE:
        await message.reply(texts.NOT_REGISTERED)
        return
    # Кнопки именные: в беседе чужой «Да» не должен что-то менять.
    await message.reply(texts.LEAVE_CONFIRM, reply_markup=leave_keyboard(user.telegram_id))


@router.callback_query(F.data.startswith("leave:"))
async def cb_leave(
    callback: CallbackQuery, session: AsyncSession, user: User, settings: Settings
) -> None:
    decision, owner_id = parse_leave_cb(callback.data or "")
    if owner_id != user.telegram_id:
        await callback.answer("Это не твоя кнопка.", show_alert=True)
        return

    if decision != "yes":
        await callback.answer()
        await callback.message.edit_text(texts.LEAVE_CANCELLED)
        return

    challenge = await challenge_service.get_current(session, settings)
    participation = (
        await participations_repo.get(session, user.id, challenge.id) if challenge else None
    )
    if participation is not None:
        await participation_service.leave(session, user, participation)
    await callback.answer()
    await callback.message.edit_text(f"{user.mention_html} — {texts.LEAVE_DONE}")
