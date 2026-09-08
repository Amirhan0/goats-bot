from __future__ import annotations

from datetime import UTC, date, datetime
from html import escape
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base
from bot.db.enums import (
    CheckinStatus,
    ParticipationStatus,
    Role,
    RsvpStatus,
    SubmissionStatus,
    TrainingStatus,
)
from bot.db.types import UTCDateTime


def _enum(py_enum: type, name: str) -> SAEnum:
    """Строковый enum без native-типа — SQLite всё равно хранит текст,
    зато CHECK-констрейнт ловит мусор."""
    return SAEnum(
        py_enum,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def display_name_of(first_name: str | None, username: str | None, telegram_id: int) -> str:
    """Как звать человека в постах.

    Имя в Telegram бывает мусорным: «-», «.», один эмодзи, пустая строка.
    В топе такое выглядит сломанным, поэтому короче двух букв — не имя,
    и мы откатываемся на @username. Функция вынесена из модели, чтобы ею
    могли пользоваться и запросы, собирающие имя без загрузки User.
    """
    name = (first_name or "").strip()
    if len(name) >= 2:
        return name
    # Ника нет — показываем id: некрасиво, но хотя бы отличает человека
    # от соседа с таким же «-». На практике не встречается: у всех,
    # у кого имя мусорное, ник есть.
    return f"@{username}" if username else str(telegram_id)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), default=Role.PARTICIPANT)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    block_reason: Mapped[str | None] = mapped_column(String(256))

    participations: Mapped[list[Participation]] = relationship(back_populates="user")

    @property
    def display_name(self) -> str:
        return display_name_of(self.first_name, self.username, self.telegram_id)

    @property
    def mention(self) -> str:
        return f"@{self.username}" if self.username else self.display_name

    @property
    def mention_html(self) -> str:
        """Кликабельное упоминание для беседы: работает и без username,
        и пингует человека, даже если он не писал боту в личку."""
        return f'<a href="tg://user?id={self.telegram_id}">{escape(self.display_name)}</a>'


class Club(Base):
    """Группа, в которой живёт бот: свой челлендж, свои тренировки, свои судьи.

    Методы намеренно повторяют одноимённые в Settings: раньше «где принимаем
    кружки» и «кто судья» отвечал конфиг, теперь отвечает клуб, а вызывающий
    код остался прежним. Настройки из .env стали значениями по умолчанию,
    из которых при первом запуске собирается первый клуб.
    """

    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)

    # 0 — топиков нет, группа обычная и весь чат считается нужной веткой.
    participants_thread_id: Mapped[int] = mapped_column(BigInteger, default=0)
    trainings_thread_id: Mapped[int] = mapped_column(BigInteger, default=0)
    checkins_thread_id: Mapped[int] = mapped_column(BigInteger, default=0)

    judges_chat_id: Mapped[int] = mapped_column(BigInteger, default=0)
    judge_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    admin_ids: Mapped[list[int]] = mapped_column(JSON, default=list)

    # Пусто — берётся общее значение из .env. Задание у каждой группы своё:
    # в одной планка, в другой что угодно ещё.
    challenge_task: Mapped[str] = mapped_column(Text, default="")
    # Призы вообще нельзя делать общими: это чужие обещания чужим людям.
    # Пусто — блок призов в правилах просто не показывается.
    prizes: Mapped[str] = mapped_column(Text, default="")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)

    def is_judge(self, telegram_id: int) -> bool:
        return telegram_id in (self.judge_ids or []) or self.is_admin(telegram_id)

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in (self.admin_ids or [])

    def _in_thread(self, own_thread: int, chat_id: int, thread_id: int | None) -> bool:
        if chat_id != self.chat_id:
            return False
        if not own_thread:
            return True
        return thread_id == own_thread

    def in_participants_thread(self, chat_id: int, thread_id: int | None) -> bool:
        return self._in_thread(self.participants_thread_id, chat_id, thread_id)

    def in_checkins_thread(self, chat_id: int, thread_id: int | None) -> bool:
        """Топик приходов не задан — значит, отдельного топика у клуба нет,
        и отчёты принимаются только реплаем на пост тренировки."""
        if not self.checkins_thread_id:
            return False
        return self._in_thread(self.checkins_thread_id, chat_id, thread_id)

    @staticmethod
    def _thread_kwargs(thread_id: int) -> dict[str, int]:
        return {"message_thread_id": thread_id} if thread_id else {}

    @property
    def participants_thread(self) -> dict[str, int]:
        return self._thread_kwargs(self.participants_thread_id)

    @property
    def trainings_thread(self) -> dict[str, int]:
        return self._thread_kwargs(self.trainings_thread_id)

    @property
    def checkins_thread(self) -> dict[str, int]:
        return self._thread_kwargs(self.checkins_thread_id)

    @property
    def checkins_chat(self) -> int:
        return self.chat_id

    @property
    def trainings_chat_id(self) -> int:
        return self.chat_id

    @property
    def participants_chat_id(self) -> int:
        return self.chat_id


class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int | None] = mapped_column(
        ForeignKey("clubs.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    rules_text: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    min_duration_sec: Mapped[int] = mapped_column(Integer, default=58)
    max_duration_sec: Mapped[int] = mapped_column(Integer, default=600)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)


class Participation(Base):
    __tablename__ = "participations"
    __table_args__ = (UniqueConstraint("user_id", "challenge_id", name="uq_participation"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    challenge_id: Mapped[int] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True
    )
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    # День челленджа на момент вступления — знаменатель процента выполнения.
    join_day: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[ParticipationStatus] = mapped_column(
        _enum(ParticipationStatus, "participation_status"),
        default=ParticipationStatus.ACTIVE,
        index=True,
    )
    left_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Кэш: источник истины — история approved-сдач (см. services/streaks.py).
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    best_streak: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped[User] = relationship(back_populates="participations", lazy="joined")
    challenge: Mapped[Challenge] = relationship(lazy="joined")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("file_unique_id", name="uq_submissions_file_unique_id"),
        UniqueConstraint(
            "participation_id", "challenge_day", "attempt_no", name="uq_submission_attempt"
        ),
        Index("ix_submissions_day_status", "challenge_day", "status"),
        Index("ix_submissions_part_day", "participation_id", "challenge_day"),
        Index("ix_submissions_judge_message", "judge_message_id"),
        Index("ix_submissions_date_status", "day_date", "status"),
        Index("ix_submissions_reviewed", "reviewed_at", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    participation_id: Mapped[int] = mapped_column(
        ForeignKey("participations.id", ondelete="CASCADE"), index=True
    )
    challenge_day: Mapped[int] = mapped_column(Integer)
    day_date: Mapped[date] = mapped_column(Date, index=True)

    # Кружок лежит в общей беседе — храним и чат, и сообщение: id беседы
    # может смениться при апгрейде группы в супергруппу.
    chat_id: Mapped[int] = mapped_column(BigInteger, default=0)
    message_id: Mapped[int] = mapped_column(BigInteger)
    file_id: Mapped[str] = mapped_column(String(256))
    file_unique_id: Mapped[str] = mapped_column(String(128))
    duration: Mapped[int] = mapped_column(Integer)
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)

    status: Mapped[SubmissionStatus] = mapped_column(
        _enum(SubmissionStatus, "submission_status"),
        default=SubmissionStatus.APPROVED,
        index=True,
    )
    reject_reason: Mapped[str | None] = mapped_column(String(256))
    judge_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    judged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # «Судья посмотрел» и «зачтено» — разные вещи: кружок зачитывается сразу,
    # поэтому очередь судей строится по непросмотренным, а не по незачтённым.
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)

    judge_message_id: Mapped[int | None] = mapped_column(BigInteger)
    judge_video_message_id: Mapped[int | None] = mapped_column(BigInteger)
    # Реплай бота с вердиктом в беседе — удаляется при откате вердикта.
    verdict_message_id: Mapped[int | None] = mapped_column(BigInteger)

    anti_cheat_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)

    undone_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    undone_by: Mapped[int | None] = mapped_column(BigInteger)

    participation: Mapped[Participation] = relationship(lazy="joined")
    judge: Mapped[User | None] = relationship(foreign_keys=[judge_id], lazy="joined")


# Уникального индекса «один зачёт в день» здесь намеренно нет: сверх
# обязательного минимума участник может сдавать сколько угодно кружков,
# и все они идут в месячный зачёт. Серия при этом считается по различным
# дням, так что второй кружок за день её не удлиняет.


class DailyCode(Base):
    __tablename__ = "daily_codes"
    __table_args__ = (UniqueConstraint("challenge_id", "date", name="uq_daily_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[int] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date, index=True)
    code: Mapped[str] = mapped_column(String(64))
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)


class Training(Base):
    """Тренировка бегового клуба.

    Отдельной таблицы шаблонов нет: «повторить» берёт последнюю подходящую
    запись отсюда же — история и есть шаблон. Меняются обычно только дата
    и время, всё остальное переносится как было.
    """

    __tablename__ = "trainings"
    __table_args__ = (
        Index("ix_trainings_start_status", "start_at", "status"),
        Index("ix_trainings_type", "training_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int | None] = mapped_column(
        ForeignKey("clubs.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    training_type: Mapped[str] = mapped_column(String(64), default="")
    location: Mapped[str] = mapped_column(String(256), default="")
    location_url: Mapped[str] = mapped_column(String(512), default="")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    # Меняется каждую неделю — единственное, что админ правит регулярно.
    weather: Mapped[str] = mapped_column(String(256), default="")
    # Многострочные списки: по пункту на строку, буллеты рисует шаблон.
    plan: Mapped[str] = mapped_column(Text, default="")
    gear: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    start_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[TrainingStatus] = mapped_column(
        _enum(TrainingStatus, "training_status"),
        default=TrainingStatus.DRAFT,
        index=True,
    )

    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    # Неанонимный опрос: Telegram сам показывает, кто как ответил, а бот
    # получает poll_answer и держит свою таблицу в синхроне.
    poll_message_id: Mapped[int | None] = mapped_column(BigInteger)
    poll_id: Mapped[str | None] = mapped_column(String(64), index=True)

    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Список уже отправленных напоминаний в часах: [3, 1]. Список, а не пара
    # булевых полей, — чтобы менять расписание напоминаний без миграции.
    reminders_sent: Mapped[list[int]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=_utcnow, onupdate=_utcnow
    )

    author: Mapped[User | None] = relationship(lazy="joined")


class TrainingParticipant(Base):
    __tablename__ = "training_participants"
    __table_args__ = (
        UniqueConstraint("training_id", "user_id", name="uq_training_participant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(
        ForeignKey("trainings.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[RsvpStatus] = mapped_column(_enum(RsvpStatus, "rsvp_status"))
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship(lazy="joined")


class TrainingCheckin(Base):
    """Отметка о приходе: скриншот Стравы реплаем на пост тренировки."""

    __tablename__ = "training_checkins"
    __table_args__ = (
        UniqueConstraint("training_id", "user_id", name="uq_training_checkin"),
        Index("ix_checkins_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(
        ForeignKey("trainings.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    chat_id: Mapped[int] = mapped_column(BigInteger, default=0)
    # Топик, из которого пришёл отчёт. Без него ответ судьи в форуме уедет
    # в General: reply_to_message_id ветку не подсказывает.
    thread_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger, default=0)
    file_id: Mapped[str] = mapped_column(String(256), default="")
    file_unique_id: Mapped[str] = mapped_column(String(128), default="")

    status: Mapped[CheckinStatus] = mapped_column(
        _enum(CheckinStatus, "checkin_status"), default=CheckinStatus.APPROVED, index=True
    )
    judge_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    judged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reject_reason: Mapped[str | None] = mapped_column(String(256))
    judge_message_id: Mapped[int | None] = mapped_column(BigInteger)

    # Ответы бота в ветке («принято», «засчитано») — их же и подчищаем.
    bot_message_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    # Проставляется после уборки, чтобы не долбиться в удалённые сообщения.
    cleaned_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)

    training: Mapped[Training] = relationship(lazy="joined")
    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")
    judge: Mapped[User | None] = relationship(foreign_keys=[judge_id], lazy="joined")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow, index=True)
