"""Несколько групп: у каждой свой челлендж, свои судьи и свои тренировки."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bot.config import settings_for_club
from bot.db.enums import TrainingStatus
from bot.db.models import Club
from bot.repositories import challenges as challenges_repo
from bot.repositories import clubs as clubs_repo
from bot.repositories import trainings as trainings_repo
from bot.services import challenge as challenge_service

NOW = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)


async def _club(session, chat_id: int, title: str, **kw) -> Club:
    club = await clubs_repo.create(session, title=title, chat_id=chat_id, **kw)
    await session.commit()
    return club


async def test_each_club_has_its_own_challenge(session, settings):
    goats = await _club(session, -100111, "GOATS")
    other = await _club(session, -100222, "Второй клуб")

    for club in (goats, other):
        await challenge_service.ensure_current(session, settings_for_club(settings, club), club)
    await session.commit()

    a = await challenge_service.get_current(session, settings_for_club(settings, goats))
    b = await challenge_service.get_current(session, settings_for_club(settings, other))

    assert a is not None and b is not None
    assert a.id != b.id  # челленджи разные
    assert a.club_id == goats.id and b.club_id == other.id
    # и создание второго не погасило первый
    assert a.is_active and b.is_active


async def test_clubs_do_not_see_each_others_trainings(session, settings):
    goats = await _club(session, -100111, "GOATS")
    other = await _club(session, -100222, "Второй клуб")

    for club, place in ((goats, "Динамо"), (other, "Парк")):
        await trainings_repo.create(
            session, club_id=club.id, title="", description="", training_type="Забег",
            location=place, start_at=NOW + timedelta(days=1),
            status=TrainingStatus.PUBLISHED, reminders_enabled=True, reminders_sent=[],
        )
    await session.commit()

    mine = await trainings_repo.upcoming(session, NOW, club_id=goats.id)
    theirs = await trainings_repo.upcoming(session, NOW, club_id=other.id)

    assert [t.location for t in mine] == ["Динамо"]
    assert [t.location for t in theirs] == ["Парк"]


async def test_judges_are_per_club(session, settings):
    goats = await _club(session, -100111, "GOATS", judge_ids=[901], judges_chat_id=-1)
    other = await _club(session, -100222, "Второй", judge_ids=[555], judges_chat_id=-2)

    a = settings_for_club(settings, goats)
    b = settings_for_club(settings, other)

    assert a.is_judge(901) and not a.is_judge(555)
    assert b.is_judge(555) and not b.is_judge(901)
    # чат судей и топики тоже свои
    assert a.judges_chat_id == -1 and b.judges_chat_id == -2
    assert a.participants_chat_id == -100111 and b.participants_chat_id == -100222


async def test_global_admin_stays_admin_everywhere(session, settings):
    """Владелец бота не должен запереть себя снаружи, забыв вписаться в клуб."""
    club = await _club(session, -100333, "Чужой", admin_ids=[42])
    scoped = settings_for_club(settings, club)

    assert scoped.is_admin(42)
    assert scoped.is_admin(settings.admin_ids[0])


async def test_unknown_chat_has_no_club(session):
    await _club(session, -100111, "GOATS")
    assert await clubs_repo.get_by_chat(session, -100999) is None


async def test_middleware_resolves_club_from_update(session, settings):
    """На уровне update в мидлварь приходит Update, а не Message.

    Проверка isinstance(event, Message) здесь молча не срабатывала, клуб
    получался None, и все группы работали по настройкам из .env — чужая
    группа показывала статистику GOATS.
    """
    from aiogram.types import Chat, Message, Update
    from aiogram.types import User as TgUser

    from bot.middlewares.club import ClubMiddleware

    club = await _club(session, -100777, "Второй клуб")
    chat = Chat(id=-100777, type="supergroup")
    tg_user = TgUser(id=42, is_bot=False, first_name="Тест")
    message = Message(message_id=1, date=NOW, chat=chat, from_user=tg_user, text="/stats")
    update = Update(update_id=1, message=message)

    seen: dict = {}

    async def handler(event, data):
        seen.update(data)

    await ClubMiddleware()(
        handler,
        update,
        {"session": session, "settings": settings, "event_chat": chat,
         "event_from_user": tg_user},
    )

    assert seen["club"] is not None and seen["club"].id == club.id
    assert seen["settings"].active_club_id == club.id
    assert seen["settings"].participants_chat_id == -100777


async def test_unknown_group_keeps_global_settings(session, settings):
    """Группа не заведена — клуба нет, и бот в ней ничего не подменяет."""
    from aiogram.types import Chat, Message, Update
    from aiogram.types import User as TgUser

    from bot.middlewares.club import ClubMiddleware

    chat = Chat(id=-100999, type="supergroup")
    tg_user = TgUser(id=42, is_bot=False, first_name="Тест")
    update = Update(
        update_id=1,
        message=Message(message_id=1, date=NOW, chat=chat, from_user=tg_user, text="/stats"),
    )

    seen: dict = {}

    async def handler(event, data):
        seen.update(data)

    await ClubMiddleware()(
        handler, update,
        {"session": session, "settings": settings, "event_chat": chat,
         "event_from_user": tg_user},
    )

    assert seen["club"] is None
    assert seen["settings"] is settings


async def test_prizes_do_not_leak_between_clubs(session, settings):
    """Призы одного клуба не должны показываться в правилах другого:
    это чужие обещания чужим людям."""
    from bot.services import challenge as challenge_service

    goats = await _club(session, -100111, "GOATS", prizes="🎁 кофе и бургер")
    other = await _club(session, -100222, "Второй клуб")

    for club in (goats, other):
        await challenge_service.ensure_current(session, settings_for_club(settings, club), club)
    await session.commit()

    a_settings = settings_for_club(settings, goats)
    b_settings = settings_for_club(settings, other)
    a = await challenge_service.get_current(session, a_settings)
    b = await challenge_service.get_current(session, b_settings)

    a_rules = challenge_service.rules_of(a, a_settings)
    b_rules = challenge_service.rules_of(b, b_settings)

    assert "кофе и бургер" in a_rules
    assert "кофе и бургер" not in b_rules
    # правила без призов остаются целыми: дисклеймер про здоровье на месте
    assert "Про здоровье" in b_rules


async def test_task_falls_back_to_global(session, settings):
    """Задание не задано — берём общее из .env, а не пустую строку."""
    own = await _club(session, -100111, "Своё", challenge_task="берпи 30 раз")
    empty = await _club(session, -100222, "Без своего")

    assert settings_for_club(settings, own).challenge_task == "берпи 30 раз"
    assert settings_for_club(settings, empty).challenge_task == settings.challenge_task


async def test_disabled_challenge_ignores_circles_and_skips_jobs(session, settings, bot):
    """Выключенный челлендж: кружки не наши, задачи челленджа молчат."""
    from types import SimpleNamespace

    from bot.filters import InParticipantsChat
    from bot.scheduler import jobs

    club = await _club(session, -100555, "Пауза", challenge_enabled=False)
    scoped = settings_for_club(settings, club)
    circle = SimpleNamespace(chat=SimpleNamespace(id=-100555), message_thread_id=None)

    assert not await InParticipantsChat()(circle, settings=scoped)
    await jobs.job_morning_post(bot, scoped)
    await jobs.job_reminder(bot, scoped)
    assert bot.calls == []  # ни одного поста в чат
