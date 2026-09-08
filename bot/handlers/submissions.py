from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.models import User
from bot.filters import InParticipantsChat
from bot.repositories import submissions as submissions_repo
from bot.services import announce as announce_service
from bot.services import submissions as submissions_service
from bot.services.anti_cheat import VideoNoteMeta
from bot.utils.timeutil import now_utc

router = Router(name="submissions")


def _is_forwarded(message: Message) -> bool:
    return bool(getattr(message, "forward_origin", None) or getattr(message, "forward_date", None))


@router.message(F.video_note, InParticipantsChat())
async def on_video_note(
    message: Message, bot: Bot, session: AsyncSession, user: User, settings: Settings
) -> None:
    """Любой кружок в общей беседе — это сдача. Отдельной команды не нужно:
    беседа заведена под челлендж, ничего другого туда не кидают."""
    video_note = message.video_note
    assert video_note is not None

    meta = VideoNoteMeta(
        duration=video_note.duration,
        file_unique_id=video_note.file_unique_id,
        is_forwarded=_is_forwarded(message),
        via_bot=message.via_bot is not None,
        # message.date уже aware-UTC; на него и опираемся, а не на время обработки
        sent_at=message.date if message.date is not None else now_utc(),
    )

    outcome = await submissions_service.accept_video_note(
        session,
        bot,
        settings,
        user=user,
        chat_id=message.chat.id,
        message_id=message.message_id,
        file_id=video_note.file_id,
        meta=meta,
    )

    # Реакция помечает статус на самом кружке, а сообщение хвалит человека —
    # это две разные вещи, поэтому идут вместе.
    if outcome.accepted and outcome.submission_id is not None:
        submission = await submissions_repo.get(session, outcome.submission_id)
        if submission is not None:
            await announce_service.mark_accepted(bot, settings, submission)

    await message.reply(outcome.text)


@router.message(F.chat.type == "private", F.video_note)
async def on_video_note_in_dm(message: Message) -> None:
    await message.answer(texts.WRONG_CHAT)


@router.message(F.chat.type == "private", F.video | F.animation | F.document | F.video_note)
async def on_wrong_media_in_dm(message: Message) -> None:
    await message.answer(texts.NOT_A_VIDEO_NOTE)


@router.message(F.video, InParticipantsChat())
async def on_plain_video_in_chat(message: Message) -> None:
    """Обычное видео вместо кружка — частая ошибка, стоит подсказать.
    На остальные сообщения в беседе бот не реагирует: это живой чат."""
    await message.reply(texts.NOT_A_VIDEO_NOTE)
