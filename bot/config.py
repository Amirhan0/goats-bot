"""Конфигурация из .env. Единственное место, где читается окружение."""

from __future__ import annotations

import logging
from datetime import date
from functools import cached_property, lru_cache
from typing import TYPE_CHECKING
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # только для аннотации: модели импортируют config
    from bot.db.models import Club

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _parse_ids(raw: str) -> tuple[int, ...]:
    out: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        out.append(int(chunk))
    return tuple(dict.fromkeys(out))  # уникальные, порядок сохранён


class Settings(BaseSettings):
    """Списки id читаются как строка и парсятся вручную: pydantic-settings
    для list[int] ждёт JSON, а в .env удобнее писать `1,2,3`."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Telegram
    bot_token: str = Field(alias="BOT_TOKEN")
    judges_chat_id: int = Field(alias="JUDGES_CHAT_ID")
    # Общая беседа: сюда участники присылают кружки, сюда же бот отвечает.
    participants_chat_id: int = Field(alias="PARTICIPANTS_CHAT_ID")
    # Если беседа — форум с топиками, кружки живут в своей ветке.
    # 0 = обычная группа или общая ветка.
    participants_thread_id: int = Field(default=0, alias="PARTICIPANTS_THREAD_ID")
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")
    judge_ids_raw: str = Field(default="", alias="JUDGE_IDS")

    # Хранилище
    db_path: Path = Field(alias="DB_PATH")
    backup_dir: Path = Field(alias="BACKUP_DIR")
    backup_keep: int = Field(default=14, alias="BACKUP_KEEP")

    # Челлендж
    timezone: str = Field(default="Asia/Almaty", alias="TIMEZONE")
    # 0 — день совпадает с календарными сутками. Ненулевое значение сдвигает
    # границу: при 4 кружок в 01:30 идёт за прошедший день.
    day_boundary_hour: int = Field(default=0, ge=0, le=23, alias="DAY_BOUNDARY_HOUR")
    challenge_start_date: date = Field(default=date(2026, 9, 1), alias="CHALLENGE_START_DATE")
    challenge_title: str = Field(default="Челлендж с кружками", alias="CHALLENGE_TITLE")
    # Что именно делают на камеру. Меняется без правки кода и миграций.
    challenge_task: str = Field(
        default="упражнение дня", alias="CHALLENGE_TASK"
    )
    # Важна только нижняя граница: кружок должен быть на полную минуту.
    # Сверху потолка фактически нет — Telegram и так ограничивает кружок
    # минутой, а длительность округляет вверх (минутный приходит как 61).
    min_duration_sec: int = Field(default=58, alias="MIN_DURATION_SEC")
    max_duration_sec: int = Field(default=600, alias="MAX_DURATION_SEC")

    # Режим
    test_mode: bool = Field(default=True, alias="TEST_MODE")
    test_start_date: date | None = Field(default=None, alias="TEST_START_DATE")

    # Слово дня
    daily_code_enabled: bool = Field(default=True, alias="DAILY_CODE_ENABLED")
    words_file: Path = Field(default=Path("data/words.txt"), alias="WORDS_FILE")
    # Высказывания, которыми бот хвалит за кружок
    quotes_file: Path = Field(default=Path("data/quotes.json"), alias="QUOTES_FILE")
    code_no_repeat_days: int = Field(default=30, alias="CODE_NO_REPEAT_DAYS")

    # ── Тренировки бегового клуба ──────────────────────────────
    club_name: str = Field(default="GOATS", alias="CLUB_NAME")
    # Не из .env: у каждого клуба свой текст, см. settings_for_club().
    prizes: str = ""
    # Общее значение по умолчанию; у клуба — своё, см. settings_for_club().
    challenge_enabled: bool = Field(default=True, alias="CHALLENGE_ENABLED")
    # Не из .env: проставляется на копии настроек под конкретный клуб,
    # см. settings_for_club(). У глобального экземпляра всегда None.
    active_club_id: int | None = None
    # 0 = чат ещё не заведён: тренировки создаются, но не публикуются.
    trainings_chat_id: int = Field(default=0, alias="TRAININGS_CHAT_ID")
    trainings_thread_id: int = Field(default=0, alias="TRAININGS_THREAD_ID")
    # За сколько часов до старта напоминать. Список, а не два флага, —
    # чтобы поменять расписание напоминаний без миграции.
    training_reminders_raw: str = Field(default="24,3", alias="TRAINING_REMINDERS")
    # Бот сам готовит черновик на регулярные дни по последней такой тренировке.
    training_auto_draft: bool = Field(default=True, alias="TRAINING_AUTO_DRAFT")
    training_draft_weekdays_raw: str = Field(
        default="tue,thu", alias="TRAINING_DRAFT_WEEKDAYS"
    )
    # Погода тянется с Open-Meteo: бесплатно, без ключа. Координаты — Алматы.
    weather_enabled: bool = Field(default=True, alias="WEATHER_ENABLED")
    weather_lat: float = Field(default=43.2389, alias="WEATHER_LAT")
    weather_lon: float = Field(default=76.8897, alias="WEATHER_LON")

    # Опрос вместо инлайн-кнопок: видно, кто как ответил, прямо в Telegram.
    use_poll: bool = Field(default=True, alias="USE_POLL")

    # Через сколько часов после тренировки убирать скриншоты и ответы бота.
    # 0 = не убирать. Пост тренировки остаётся всегда.
    checkin_cleanup_hours: int = Field(default=24, alias="CHECKIN_CLEANUP_HOURS")
    # Отдельный топик под отчёты. Там реплай на пост не нужен — приход
    # привязывается к последней прошедшей тренировке сам.
    checkins_chat_id: int = Field(default=0, alias="CHECKINS_CHAT_ID")
    checkins_thread_id: int = Field(default=0, alias="CHECKINS_THREAD_ID")
    # Сколько часов после начала тренировки принимаем по ней отчёты. Окно
    # и есть защита от «че попало»: нет прошедшей тренировки — нечего
    # засчитывать, и фото остаётся просто фото.
    checkin_window_hours: int = Field(default=48, ge=1, alias="CHECKIN_WINDOW_HOURS")

    # Реакции вместо сообщений «принято» — меньше шума в беседе
    use_reactions: bool = Field(default=True, alias="USE_REACTIONS")

    # Очередь судей

    # Лимиты
    submission_cooldown_sec: int = Field(default=30, alias="SUBMISSION_COOLDOWN_SEC")
    last_minutes_flag: int = Field(default=15, alias="LAST_MINUTES_FLAG")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("test_start_date", mode="before")
    @classmethod
    def _empty_date_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("db_path", "backup_dir")
    @classmethod
    def _must_be_absolute(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError(f"путь должен быть абсолютным, получено: {v}")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz_exists(cls, v: str) -> str:
        ZoneInfo(v)  # бросит ZoneInfoNotFoundError, если зоны нет
        return v

    # ── производные ────────────────────────────────────────────

    @cached_property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @cached_property
    def admin_ids(self) -> tuple[int, ...]:
        return _parse_ids(self.admin_ids_raw)

    @cached_property
    def judge_ids(self) -> tuple[int, ...]:
        """Админы автоматически считаются судьями."""
        return tuple(dict.fromkeys(_parse_ids(self.judge_ids_raw) + self.admin_ids))

    @cached_property
    def words_path(self) -> Path:
        return self._resolve(self.words_file)

    @cached_property
    def quotes_path(self) -> Path:
        return self._resolve(self.quotes_file)

    def _resolve(self, p: Path) -> Path:
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def primary_admin_id(self) -> int | None:
        return self.admin_ids[0] if self.admin_ids else None

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_ids

    def is_judge(self, telegram_id: int) -> bool:
        return telegram_id in self.judge_ids

    def is_participants_chat(self, chat_id: int) -> bool:
        return chat_id == self.participants_chat_id

    def in_participants_thread(self, chat_id: int, thread_id: int | None) -> bool:
        """В форуме кружки принимаем только из своей ветки: иначе кружок,
        брошенный в топик тренировок, тоже уехал бы в зачёт."""
        if chat_id != self.participants_chat_id:
            return False
        if not self.participants_thread_id:
            return True
        return thread_id == self.participants_thread_id

    @property
    def participants_thread(self) -> dict[str, int]:
        """Готовый kwargs для send_message: пустой, если топиков нет."""
        return (
            {"message_thread_id": self.participants_thread_id}
            if self.participants_thread_id
            else {}
        )

    @property
    def trainings_thread(self) -> dict[str, int]:
        return (
            {"message_thread_id": self.trainings_thread_id}
            if self.trainings_thread_id
            else {}
        )

    @property
    def checkins_chat(self) -> int:
        """Топик приходов не задан — работаем по-старому, в ветке тренировок."""
        return self.checkins_chat_id or self.trainings_chat_id

    @property
    def checkins_thread(self) -> dict[str, int]:
        return (
            {"message_thread_id": self.checkins_thread_id}
            if self.checkins_thread_id
            else {}
        )

    def in_checkins_thread(self, chat_id: int, thread_id: int | None) -> bool:
        """Свой топик под отчёты: фото оттуда — заявка на приход, и реплай
        на пост тренировки для этого не нужен."""
        if not self.checkins_thread_id or chat_id != self.checkins_chat:
            return False
        return thread_id == self.checkins_thread_id

    @property
    def trainings_enabled(self) -> bool:
        """Пока чат клуба не задан, тренировки живут только в личке админа."""
        return bool(self.trainings_chat_id)

    @cached_property
    def training_reminders(self) -> tuple[int, ...]:
        """Часы до старта, отсортированы по убыванию: сначала «за 3», потом «за 1»."""
        hours = {int(x) for x in _parse_ids(self.training_reminders_raw) if int(x) > 0}
        return tuple(sorted(hours, reverse=True))

    @cached_property
    def training_draft_weekdays(self) -> tuple[int, ...]:
        """Дни недели для авто-черновиков в формате datetime.weekday(): пн=0."""
        names = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        out = {
            names.index(chunk)
            for chunk in self.training_draft_weekdays_raw.lower().replace(" ", "").split(",")
            if chunk in names
        }
        return tuple(sorted(out))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()  # type: ignore[call-arg]
    s.db_path.parent.mkdir(parents=True, exist_ok=True)
    s.backup_dir.mkdir(parents=True, exist_ok=True)
    if not s.admin_ids:
        logger.warning("ADMIN_IDS пуст — админские команды будут недоступны никому")
    return s


def settings_for_club(settings: Settings, club: "Club") -> Settings:
    """Настройки, «наведённые» на конкретный клуб.

    Весь код ниже уровня хендлеров спрашивает у Settings, куда постить и кто
    судья. Раньше ответ был один на всю установку; теперь на каждый апдейт
    берётся копия, в которой чаты, топики и судьи подменены клубными. Так
    сервисы, планировщик и тексты не пришлось переписывать под второй
    аргумент — они по-прежнему получают один объект и работают с ним.

    Копия обязана быть свежей: admin_ids и judge_ids — cached_property,
    и унаследованный от родителя кэш подсунул бы чужих судей.
    """
    scoped = settings.model_copy(
        update={
            "active_club_id": club.id,
            "club_name": club.title or settings.club_name,
            "challenge_task": club.challenge_task or settings.challenge_task,
            "prizes": club.prizes,
            "challenge_enabled": club.challenge_enabled,
            "participants_chat_id": club.chat_id,
            "participants_thread_id": club.participants_thread_id,
            "trainings_chat_id": club.chat_id,
            "trainings_thread_id": club.trainings_thread_id,
            "checkins_chat_id": club.chat_id,
            "checkins_thread_id": club.checkins_thread_id,
            "judges_chat_id": club.judges_chat_id,
            "judge_ids_raw": ",".join(str(i) for i in (club.judge_ids or [])),
            # Глобальные админы из .env остаются админами везде: иначе владелец
            # бота потерял бы доступ к клубу, забыв вписать себя в его список.
            "admin_ids_raw": ",".join(
                str(i) for i in dict.fromkeys([*(club.admin_ids or []), *settings.admin_ids])
            ),
        }
    )
    for cached in ("admin_ids", "judge_ids"):
        scoped.__dict__.pop(cached, None)
    return scoped
