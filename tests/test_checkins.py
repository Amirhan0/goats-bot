"""Приходы: один на тренировку, пересдача после отказа, рейтинг."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bot.utils.timeutil import now_utc

from bot.db.enums import CheckinStatus, TrainingStatus
from bot.db.models import User
from bot.repositories import checkins as checkins_repo
from bot.repositories import trainings as trainings_repo
from bot.services import checkins as checkins_service
from bot.services import trainings as trainings_service

PAST = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)
SEPT = datetime(2026, 9, 1, tzinfo=UTC)


async def _training(session, when=PAST, **kw):
    t = await trainings_repo.create(
        session, title="", description="", training_type="Интервальная",
        location="Стадион", start_at=when, status=TrainingStatus.PUBLISHED,
        reminders_enabled=True, reminders_sent=[], **kw,
    )
    await session.commit()
    return t


async def _user(session, tg: int) -> User:
    u = User(telegram_id=tg, username=f"u{tg}", first_name=f"U{tg}")
    session.add(u)
    await session.commit()
    return u


async def _checkin(session, training, user, status=CheckinStatus.APPROVED):
    c = await checkins_repo.create(
        session, training_id=training.id, user_id=user.id,
        chat_id=-100, message_id=1, file_id="f", file_unique_id=f"u{training.id}-{user.id}",
    )
    c.status = status
    await session.commit()
    return c


async def test_one_checkin_per_training(session, settings, bot):
    training = await _training(session)
    user = await _user(session, 4001)
    await _checkin(session, training, user)

    result = await checkins_service.accept_photo(
        session, bot, settings, training=training, user=user,
        chat_id=-100, message_id=2, file_id="f2", file_unique_id="u2",
    )

    assert not result.ok
    assert "уже засчитан" in result.text


async def test_rejected_checkin_can_be_resent(session, settings, bot):
    """Отмена не блокирует: новый скриншот сразу снова в зачёте."""
    training = await _training(session)
    user = await _user(session, 4002)
    first = await _checkin(session, training, user, status=CheckinStatus.REJECTED)

    result = await checkins_service.accept_photo(
        session, bot, settings, training=training, user=user,
        chat_id=-100, message_id=9, file_id="new", file_unique_id="new",
    )

    assert result.ok
    again = await checkins_repo.get_for(session, training.id, user.id)
    assert again.id == first.id  # та же запись, а не вторая
    assert again.status == CheckinStatus.APPROVED
    assert again.file_id == "new"


async def test_checkin_before_training_is_rejected(session, settings, bot):
    future = await _training(session, when=datetime(2099, 1, 1, tzinfo=UTC))
    user = await _user(session, 4003)

    result = await checkins_service.accept_photo(
        session, bot, settings, training=future, user=user,
        chat_id=-100, message_id=3, file_id="f", file_unique_id="f",
    )

    assert not result.ok
    assert "ещё не началась" in result.text


async def test_only_approved_count_in_rating(session, settings):
    training = await _training(session)
    good = await _user(session, 4010)
    bad = await _user(session, 4011)
    await _checkin(session, training, good, status=CheckinStatus.APPROVED)
    await _checkin(session, training, bad, status=CheckinStatus.PENDING)

    rows = await checkins_repo.leaderboard(session)

    assert [(r.name, r.visits) for r in rows] == [("U4010", 1)]


async def test_rating_counts_visits_across_trainings(session, settings):
    user = await _user(session, 4020)
    for shift in (0, 2, 4):
        training = await _training(session, when=PAST + timedelta(days=shift))
        await _checkin(session, training, user)

    assert (await checkins_repo.leaderboard(session))[0].visits == 3
    assert await checkins_repo.count_for_user(session, user.id) == 3


async def test_monthly_rating_ignores_other_months(session, settings):
    user = await _user(session, 4030)
    august = await _training(session, when=datetime(2026, 8, 25, 14, 0, tzinfo=UTC))
    september = await _training(session, when=datetime(2026, 9, 2, 14, 0, tzinfo=UTC))
    await _checkin(session, august, user)
    await _checkin(session, september, user)

    assert await checkins_repo.count_for_user(session, user.id) == 2
    assert await checkins_repo.count_for_user(session, user.id, since=SEPT) == 1


async def test_cleanup_removes_only_judged(session, settings, bot):
    """Непроверенный скриншот — единственное доказательство человека.
    Удалять его нельзя, даже если тренировка была давно."""
    old = await _training(session, when=datetime(2026, 8, 1, 14, 0, tzinfo=UTC))
    judged_user = await _user(session, 5001)
    waiting_user = await _user(session, 5002)
    judged = await _checkin(session, old, judged_user, status=CheckinStatus.APPROVED)
    waiting = await _checkin(session, old, waiting_user, status=CheckinStatus.PENDING)

    removed = await checkins_service.cleanup(session, bot, settings)

    assert removed == 1
    assert (await checkins_repo.get(session, judged.id)).cleaned_at is not None
    assert (await checkins_repo.get(session, waiting.id)).cleaned_at is None


async def test_cleanup_deletes_screenshot_and_bot_replies(session, settings, bot):
    old = await _training(session, when=datetime(2026, 8, 1, 14, 0, tzinfo=UTC))
    user = await _user(session, 5003)
    checkin = await _checkin(session, old, user)
    await checkins_repo.remember_bot_message(session, checkin, 777)
    await session.commit()

    await checkins_service.cleanup(session, bot, settings)

    deleted = [kw["message_id"] for name, kw in bot.calls if name == "delete_message"]
    assert checkin.message_id in deleted  # сам скриншот
    assert 777 in deleted                 # и ответ бота


async def test_cleanup_keeps_fresh_trainings(session, settings, bot):
    fresh = await _training(session, when=datetime(2099, 1, 1, tzinfo=UTC) - timedelta(days=1))
    user = await _user(session, 5004)
    await _checkin(session, fresh, user)

    assert await checkins_service.cleanup(session, bot, settings) == 0


async def test_cleanup_disabled_by_setting(session, settings, bot):
    old = await _training(session, when=datetime(2026, 8, 1, 14, 0, tzinfo=UTC))
    await _checkin(session, old, await _user(session, 5005))

    off = settings.model_copy(update={"checkin_cleanup_hours": 0})
    assert await checkins_service.cleanup(session, bot, off) == 0


async def test_checkin_window_follows_training_time(session, settings, bot):
    """Пост могли опубликовать за неделю до занятия — окно открывает время
    самой тренировки, а не дата публикации и не дата скриншота."""
    training = await _training(session, when=PAST, message_id=15174, poll_message_id=15175)
    user = await _user(session, 4020)

    result = await checkins_service.accept_photo(
        session, bot, settings, training=training, user=user,
        chat_id=-100, message_id=77, file_id="f", file_unique_id="late",
    )

    assert result.ok
    # и тот же пост находится по реплаю как в него самого, так и в опрос
    assert (await trainings_repo.get_by_message(session, 15175)).id == training.id


async def test_purge_removes_training_with_its_messages(session, settings, bot):
    """Удаление тренировки уносит пост, опрос, скриншоты и сами приходы."""
    training = await _training(session, message_id=800, poll_message_id=801)
    user = await _user(session, 4030)
    checkin = await _checkin(session, training, user)
    await checkins_repo.remember_bot_message(session, checkin, 803)
    checkin.message_id = 802
    await session.commit()

    removed = await trainings_service.purge(session, bot, settings, training)

    deleted = {kw["message_id"] for name, kw in bot.calls if name == "delete_message"}
    assert deleted == {800, 801, 802, 803}
    assert removed == 4
    assert await trainings_repo.get(session, training.id) is None
    # приход ушёл вместе с тренировкой: ON DELETE CASCADE в схеме
    assert await checkins_repo.get(session, checkin.id) is None


async def test_checkin_counts_without_judge(session, settings, bot):
    """Приход засчитывается сразу и попадает в рейтинг без вердикта судьи."""
    training = await _training(session)
    user = await _user(session, 4040)

    result = await checkins_service.accept_photo(
        session, bot, settings, training=training, user=user,
        chat_id=-100, message_id=5, file_id="f", file_unique_id="auto",
    )

    assert result.ok
    checkin = await checkins_repo.get_for(session, training.id, user.id)
    assert checkin.status == CheckinStatus.APPROVED
    assert checkin.judge_id is None  # никто ничего не нажимал
    rows = await checkins_repo.leaderboard(session)
    assert [(r.telegram_id, r.visits) for r in rows] == [(4040, 1)]


async def test_match_picks_recent_training_without_reply(session, settings):
    """В топике приходов реплая нет — занятие ищется по времени."""
    now = now_utc()
    await _training(session, when=now - timedelta(days=10))   # вне окна
    fresh = await _training(session, when=now - timedelta(hours=3))
    user = await _user(session, 4041)

    matched = await checkins_service.match_training(session, settings, user)

    assert matched is not None and matched.id == fresh.id


async def test_match_falls_back_to_previous_training(session, settings, bot):
    """Сходил на две подряд — второй скриншот уходит на предыдущую."""
    now = now_utc()
    older = await _training(session, when=now - timedelta(hours=30))
    newer = await _training(session, when=now - timedelta(hours=3))
    user = await _user(session, 4042)

    await checkins_service.accept_photo(
        session, bot, settings, training=newer, user=user,
        chat_id=-100, message_id=6, file_id="f", file_unique_id="one",
    )

    assert (await checkins_service.match_training(session, settings, user)).id == older.id


async def test_no_training_in_window_means_no_checkin(session, settings):
    """Случайное фото не должно ничего засчитывать: тренировки не было."""
    await _training(session, when=now_utc() - timedelta(days=10))
    user = await _user(session, 4043)

    assert await checkins_service.match_training(session, settings, user) is None
