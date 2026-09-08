from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import Settings  # noqa: E402
from bot.db.base import Base  # noqa: E402
from bot.db.enums import ParticipationStatus, Role  # noqa: E402
from bot.db.models import Challenge, Participation, Submission, User  # noqa: E402
from bot.db.session import dispose_engine, get_sessionmaker, init_engine  # noqa: E402

TEST_START = date(2026, 9, 1)
PARTICIPANTS_CHAT = -1003333333333
TRAININGS_CHAT = -1004444444444


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Значения передаём по АЛИАСАМ и с _env_file=None.

    Поля объявлены как Field(alias="DB_PATH"), и передача по имени поля
    молча игнорируется — выигрывает .env из корня проекта. Однажды это уже
    привело к тому, что тесты отработали по боевой базе. Проверка внизу
    не даёт этому повториться незаметно.
    """
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        BOT_TOKEN="123:TEST",
        JUDGES_CHAT_ID=-1001111111111,
        PARTICIPANTS_CHAT_ID=PARTICIPANTS_CHAT,
        TRAININGS_CHAT_ID=TRAININGS_CHAT,
        ADMIN_IDS="900",
        JUDGE_IDS="901,902",
        DB_PATH=tmp_path / "bot.db",
        BACKUP_DIR=tmp_path / "backups",
        TIMEZONE="Asia/Almaty",
        DAY_BOUNDARY_HOUR=4,
        CHALLENGE_START_DATE=TEST_START,
        TEST_MODE=False,
        DAILY_CODE_ENABLED=False,
        WORDS_FILE=Path("data/words.txt"),
    )
    assert settings.db_path.is_relative_to(tmp_path), (
        f"тесты смотрят в {settings.db_path} вместо временной базы — "
        "настройки не переопределились"
    )
    return settings


@pytest_asyncio.fixture
async def sessionmaker(settings: Settings):
    engine = init_engine(settings.db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield get_sessionmaker()
    await dispose_engine()


@pytest_asyncio.fixture
async def session(sessionmaker):
    async with sessionmaker() as s:
        yield s


class FakeBot:
    """Телеграм замокан: методы ничего не делают, но записывают вызовы."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._next_message_id = 1000

    def _record(self, name: str, kwargs: dict):
        self.calls.append((name, kwargs))
        self._next_message_id += 1
        return SimpleNamespace(message_id=self._next_message_id, chat=SimpleNamespace(id=1))

    async def send_message(self, **kwargs):
        return self._record("send_message", kwargs)

    async def send_video_note(self, **kwargs):
        return self._record("send_video_note", kwargs)

    async def copy_message(self, **kwargs):
        return self._record("copy_message", kwargs)

    async def edit_message_text(self, **kwargs):
        return self._record("edit_message_text", kwargs)

    async def delete_message(self, **kwargs):
        return self._record("delete_message", kwargs)

    async def set_message_reaction(self, **kwargs):
        return self._record("set_message_reaction", kwargs)

    async def send_poll(self, **kwargs):
        sent = self._record("send_poll", kwargs)
        # У настоящего ответа poll.id — строка и она не равна message_id:
        # тренировка ищется по ней, поэтому подделываем ту же форму.
        sent.poll = SimpleNamespace(id=f"poll-{sent.message_id}")
        return sent

    async def stop_poll(self, **kwargs):
        return self._record("stop_poll", kwargs)

    def sent_to(self, chat_id: int) -> list[dict]:
        return [kw for name, kw in self.calls if kw.get("chat_id") == chat_id]


@pytest.fixture
def bot() -> FakeBot:
    return FakeBot()


@pytest_asyncio.fixture
async def challenge(session) -> Challenge:
    item = Challenge(
        title="Тест",
        description="",
        rules_text="",
        start_date=TEST_START,
        min_duration_sec=59,
        max_duration_sec=60,
        is_test=False,
        is_active=True,
    )
    session.add(item)
    await session.commit()
    return item


async def make_participant(
    session, challenge: Challenge, telegram_id: int, join_day: int = 1
) -> Participation:
    user = User(telegram_id=telegram_id, username=f"u{telegram_id}", first_name=f"U{telegram_id}")
    session.add(user)
    await session.flush()
    participation = Participation(
        user_id=user.id,
        challenge_id=challenge.id,
        join_day=join_day,
        status=ParticipationStatus.ACTIVE,
    )
    session.add(participation)
    await session.commit()
    return participation


async def make_judge(session, telegram_id: int) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"judge{telegram_id}",
        first_name=f"Judge{telegram_id}",
        role=Role.JUDGE,
    )
    session.add(user)
    await session.commit()
    return user


async def make_submission(
    session,
    participation: Participation,
    day: int,
    *,
    file_unique_id: str | None = None,
    attempt_no: int = 1,
    sent_at: datetime | None = None,
) -> Submission:
    submission = Submission(
        participation_id=participation.id,
        challenge_day=day,
        day_date=TEST_START + timedelta(days=day - 1),
        chat_id=PARTICIPANTS_CHAT,
        message_id=100 + day,
        file_id=f"file-{participation.id}-{day}-{attempt_no}",
        file_unique_id=file_unique_id or f"uniq-{participation.id}-{day}-{attempt_no}",
        duration=60,
        sent_at=sent_at or datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        attempt_no=attempt_no,
        anti_cheat_flags=[],
    )
    session.add(submission)
    await session.commit()
    return submission
