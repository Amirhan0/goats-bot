from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    PARTICIPANT = "participant"
    JUDGE = "judge"
    ADMIN = "admin"


class ParticipationStatus(StrEnum):
    ACTIVE = "active"
    DROPPED = "dropped"


class SubmissionStatus(StrEnum):
    """Кружок зачитывается сразу; судья потом либо подтверждает, либо отменяет.

    APPROVED — зачтено: идёт и в дни (серия), и в месячный счёт кружков.
    REJECTED — отменено, пока день ещё шёл: не идёт никуда, можно переснять.
    REVOKED  — отменено уже после закрытия дня: уходит из месячного счёта,
               но день остаётся закрытым, серия не рвётся задним числом.
    PENDING  — исторический статус старых записей; новые не создаются.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"

    @classmethod
    def crediting_day(cls) -> tuple[SubmissionStatus, ...]:
        """Статусы, при которых день считается закрытым."""
        return (cls.APPROVED, cls.REVOKED)


class RejectReason(StrEnum):
    """Причины незачёта, доступные судье одной кнопкой."""

    NO_CODE_WORD = "no_code_word"
    OFF_TOPIC = "off_topic"
    TOO_SHORT = "too_short"
    REPEAT = "repeat"
    EDITED = "edited"
    CUSTOM = "custom"


class TrainingStatus(StrEnum):
    DRAFT = "draft"          # создана, в чат не ушла
    PUBLISHED = "published"  # опубликована, идёт сбор участников
    CANCELLED = "cancelled"  # отменена админом


class RsvpStatus(StrEnum):
    GOING = "going"
    MAYBE = "maybe"
    NOT_GOING = "not_going"


class CheckinStatus(StrEnum):
    """Приход на тренировку по скриншоту Стравы.

    Здесь, в отличие от кружков, ждём судью: скриншот проверить сложнее,
    и «зачтено авансом» дало бы приписки в рейтинге приходов.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AuditAction(StrEnum):
    JOIN = "join"
    LEAVE = "leave"
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    UNDO = "undo"
    BAN = "ban"
    UNBAN = "unban"
    SET_CODE = "set_code"
    BROADCAST = "broadcast"
    EXPORT = "export"
    SIMULATE_DAY = "simulate_day"
    WIPE_TEST = "wipe_test"
    DAY_CLOSED = "day_closed"
    PUBLISH_FAILED = "publish_failed"
    TRAINING_CREATED = "training_created"
    TRAINING_UPDATED = "training_updated"
    TRAINING_PUBLISHED = "training_published"
    TRAINING_CANCELLED = "training_cancelled"
    CHECKIN_SENT = "checkin_sent"
    CHECKIN_APPROVED = "checkin_approved"
    CHECKIN_REJECTED = "checkin_rejected"
