"""Тренировки: один ответ на человека, повтор из истории, авто-черновик."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bot.db.enums import RsvpStatus, TrainingStatus
from bot.db.models import User
from bot.repositories import trainings as trainings_repo
from bot.services import trainings as trainings_service

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)  # чт, 14:00 по Алматы


async def _training(session, settings, *, days: int = 1, **kwargs):
    base = dict(
        title="",
        description="6×400",
        training_type="Интервальная",
        location="Центральный стадион",
        start_at=NOW + timedelta(days=days),
        status=TrainingStatus.PUBLISHED,
        reminders_enabled=True,
        reminders_sent=[],
    )
    training = await trainings_repo.create(session, **{**base, **kwargs})
    await session.commit()
    return training


async def _user(session, telegram_id: int) -> User:
    user = User(telegram_id=telegram_id, username=f"u{telegram_id}", first_name=f"U{telegram_id}")
    session.add(user)
    await session.commit()
    return user


async def test_one_answer_per_person(session, settings):
    training = await _training(session, settings)
    user = await _user(session, 1001)

    await trainings_repo.set_rsvp(session, training.id, user.id, RsvpStatus.GOING)
    await trainings_repo.set_rsvp(session, training.id, user.id, RsvpStatus.NOT_GOING)
    await session.commit()

    counts = await trainings_repo.counts(session, training.id)
    assert counts["going"] == 0
    assert counts["not_going"] == 1
    assert len(await trainings_repo.participants(session, training.id)) == 1


async def test_counts_split_by_status(session, settings):
    training = await _training(session, settings)
    for i, status in enumerate(
        [RsvpStatus.GOING, RsvpStatus.GOING, RsvpStatus.MAYBE, RsvpStatus.NOT_GOING]
    ):
        user = await _user(session, 2000 + i)
        await trainings_repo.set_rsvp(session, training.id, user.id, status)
    await session.commit()

    counts = await trainings_repo.counts(session, training.id)
    assert (counts["going"], counts["maybe"], counts["not_going"]) == (2, 1, 1)


async def test_only_going_get_reminders(session, settings):
    training = await _training(session, settings)
    going = await _user(session, 3001)
    maybe = await _user(session, 3002)
    await trainings_repo.set_rsvp(session, training.id, going.id, RsvpStatus.GOING)
    await trainings_repo.set_rsvp(session, training.id, maybe.id, RsvpStatus.MAYBE)
    await session.commit()

    assert await trainings_repo.going_telegram_ids(session, training.id) == [3001]


async def test_repeat_copies_everything_but_time(session, settings):
    source = await _training(session, settings, days=-7)
    new_start = source.start_at + timedelta(days=7)

    copy = await trainings_service.copy_for_repeat(session, source, new_start, None)
    await session.commit()

    assert copy.id != source.id
    assert copy.location == source.location
    assert copy.training_type == source.training_type
    assert copy.description == source.description
    assert copy.start_at == new_start
    assert copy.status == TrainingStatus.DRAFT  # публикуем вручную
    assert copy.reminders_sent == []


async def test_auto_draft_uses_same_weekday(session, settings, monkeypatch):
    """Вторник берётся по прошлому вторнику, а не по последней тренировке."""
    # Время замораживаем: auto_draft ищет ближайший вт/чт от «сейчас», и без
    # этого тест падал в те дни, когда следующим по календарю шёл четверг.
    monkeypatch.setattr(
        trainings_service, "now_utc", lambda: datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
    )
    tuesday = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)   # вт
    thursday = datetime(2026, 8, 27, 2, 0, tzinfo=UTC)   # чт, уже прошёл
    await _training(session, settings, days=0, start_at=tuesday, location="Стадион ВТ")
    await _training(session, settings, days=0, start_at=thursday, location="Парк ЧТ")

    draft = await trainings_service.auto_draft(session, settings, ahead_days=7)

    assert draft is not None
    assert draft.location == "Стадион ВТ"
    assert draft.start_at.astimezone(settings.tz).weekday() == 1
    assert draft.status == TrainingStatus.DRAFT


async def test_auto_draft_skips_day_that_already_has_training(session, settings):
    tuesday = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)
    await _training(session, settings, days=0, start_at=tuesday)
    # Уже есть будущая тренировка на ближайший вторник.
    await _training(session, settings, days=0, start_at=datetime(2026, 9, 1, 14, 0, tzinfo=UTC))

    draft = await trainings_service.auto_draft(session, settings, ahead_days=7)

    assert draft is None or draft.start_at != datetime(2026, 9, 1, 14, 0, tzinfo=UTC)


def test_weather_phrase_matches_club_style() -> None:
    from bot.services.weather import Forecast

    # Ясно и сухо — только градусы, лишних слов не добавляем.
    assert Forecast(temperature=25.4, code=0, precipitation=5).describe() == "около 25°C"
    # Осадки уже в описании кода — «возможен дождь» было бы дублем.
    assert Forecast(temperature=22.0, code=63, precipitation=90).describe() == "около 22°C, дождь"
    # Сухой код, но высокая вероятность — предупреждаем.
    assert (
        Forecast(temperature=25.0, code=2, precipitation=60).describe()
        == "около 25°C, возможен дождь"
    )
    assert Forecast(temperature=19.6, code=95, precipitation=80).describe() == "около 20°C, гроза"


def test_unknown_weather_code_does_not_crash() -> None:
    from bot.services.weather import Forecast

    assert Forecast(temperature=10.0, code=1234, precipitation=0).describe() == "около 10°C"


def test_type_shown_only_without_plan() -> None:
    """У клуба тип зашит в план. Но у быстрой тренировки плана нет —
    и без типа пост не сказал бы, что происходит."""
    from bot import texts

    quick = texts.training_post(
        weekday="в субботу", day="30 августа", clock="08:00",
        training_type="Забег", location="Парк",
    )
    assert "🔥 <b>Забег</b>" in quick

    full = texts.training_post(
        weekday="во вторник", day="1 сентября", clock="19:30",
        training_type="Интервальная", plan="интервалы\nотрезки", location="Стадион",
    )
    assert "🔥" not in full
    assert "• интервалы" in full


async def test_poll_answer_maps_option_to_status(session, settings):
    """Порядок вариантов опроса жёстко связан со статусами: Telegram
    присылает индекс, а не текст."""
    from bot import texts

    training = await _training(session, settings)
    user = await _user(session, 6001)

    for index, expected in enumerate(texts.POLL_ORDER):
        await trainings_service.apply_poll_answer(session, training, user.id, [index])
        await session.commit()
        rows = await trainings_repo.participants(session, training.id)
        assert len(rows) == 1, "ответ должен оставаться один"
        assert rows[0].status.value == expected


async def test_retracted_vote_removes_participant(session, settings):
    """Отозвал голос — убираем и у себя, иначе напоминание уйдёт тому,
    кто уже передумал."""
    training = await _training(session, settings)
    user = await _user(session, 6002)
    await trainings_service.apply_poll_answer(session, training, user.id, [0])
    await session.commit()

    await trainings_service.apply_poll_answer(session, training, user.id, [])
    await session.commit()

    assert await trainings_repo.participants(session, training.id) == []
    assert await trainings_repo.going_telegram_ids(session, training.id) == []


def test_poll_options_match_status_order() -> None:
    from bot import texts

    assert texts.POLL_ORDER == ("going", "maybe", "not_going")
    assert texts.POLL_OPTIONS == ["💪 Буду", "🤔 Возможно", "❌ Не буду"]


async def test_reply_to_poll_finds_training(session, settings):
    """Скриншот кидают реплаем в опрос не реже, чем в сам пост."""
    training = await _training(session, settings, message_id=500, poll_message_id=501)

    by_post = await trainings_repo.get_by_message(session, 500)
    by_poll = await trainings_repo.get_by_message(session, 501)

    assert by_post is not None and by_post.id == training.id
    assert by_poll is not None and by_poll.id == training.id
    assert await trainings_repo.get_by_message(session, 999) is None


async def test_republish_moves_post_and_keeps_answers(session, settings, bot):
    """Повторная публикация поднимает пост: старые сообщения убираются,
    новые уходят в чат. Ответы участников при этом не теряются."""
    training = await _training(session, settings, message_id=900, poll_message_id=901)
    user = await _user(session, 1010)
    await trainings_repo.set_rsvp(session, training.id, user.id, RsvpStatus.GOING)
    await session.commit()

    result = await trainings_service.republish(session, bot, settings, training, actor_id=1)
    await session.commit()

    assert result.ok
    deleted = {kw["message_id"] for name, kw in bot.calls if name == "delete_message"}
    assert deleted == {900, 901}
    assert training.message_id not in (None, 900)  # пост уехал вниз ветки
    counts = await trainings_repo.counts(session, training.id)
    assert counts.get("going") == 1  # «Буду» пережило перепубликацию
