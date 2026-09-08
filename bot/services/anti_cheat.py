"""Автоматические проверки кружка.

Чистые функции: на вход — метаданные сообщения и заранее собранный контекст,
на выход — вердикт и список флагов. Ни БД, ни сети, ни aiogram-типов, чтобы
всё это можно было прогнать юнит-тестами.

Важно: Telegram не отдаёт признак «записано только что». Задача этого модуля —
отсечь дешёвые подделки (пересылка, повтор файла, неверная длительность),
остальное подсвечивается флагами и решается судьёй.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RejectCode(StrEnum):
    NOT_VIDEO_NOTE = "not_video_note"
    FORWARDED = "forwarded"
    BAD_DURATION = "bad_duration"
    DUPLICATE = "duplicate"
    NOT_REGISTERED = "not_registered"
    LEFT_CHALLENGE = "left_challenge"
    BLOCKED = "blocked"
    CHALLENGE_INACTIVE = "challenge_inactive"
    NOT_STARTED = "not_started"
    FINISHED = "finished"


class FlagCode(StrEnum):
    LAST_MINUTES = "last_minutes"
    VIA_BOT = "via_bot"
    MANY_ATTEMPTS = "many_attempts"
    FAST_RETRY = "fast_retry"


@dataclass(frozen=True, slots=True)
class VideoNoteMeta:
    """То, что реально приходит от Telegram."""

    duration: int
    file_unique_id: str
    is_forwarded: bool
    via_bot: bool
    sent_at: datetime


@dataclass(frozen=True, slots=True)
class SubmissionContext:
    """Состояние мира на момент приёма кружка — собирает вызывающий сервис."""

    is_registered: bool
    participation_active: bool
    user_blocked: bool
    challenge_active: bool
    challenge_started: bool
    challenge_finished: bool
    min_duration: int
    max_duration: int
    duplicate_exists: bool
    current_day: int
    seconds_to_deadline: int
    attempt_no: int
    seconds_since_prev_attempt: int | None = None
    last_minutes_flag: int = 15


@dataclass(frozen=True, slots=True)
class CheckResult:
    ok: bool
    reject: RejectCode | None = None
    flags: tuple[FlagCode, ...] = field(default_factory=tuple)

    @property
    def flag_values(self) -> list[str]:
        return [f.value for f in self.flags]


def collect_flags(meta: VideoNoteMeta, ctx: SubmissionContext) -> tuple[FlagCode, ...]:
    """Флаги не блокируют приём — они подсвечиваются судье в карточке."""
    flags: list[FlagCode] = []

    if 0 <= ctx.seconds_to_deadline <= ctx.last_minutes_flag * 60:
        flags.append(FlagCode.LAST_MINUTES)
    if meta.via_bot:
        flags.append(FlagCode.VIA_BOT)
    if ctx.attempt_no >= 3:
        flags.append(FlagCode.MANY_ATTEMPTS)
    if ctx.seconds_since_prev_attempt is not None and ctx.seconds_since_prev_attempt < 60:
        flags.append(FlagCode.FAST_RETRY)

    return tuple(flags)


def check_submission(meta: VideoNoteMeta, ctx: SubmissionContext) -> CheckResult:
    """Порядок проверок = порядок, в котором участник увидит причину отказа.
    Сначала блокирующие состояния, потом свойства самого кружка."""

    if ctx.user_blocked:
        return CheckResult(ok=False, reject=RejectCode.BLOCKED)
    if not ctx.is_registered:
        return CheckResult(ok=False, reject=RejectCode.NOT_REGISTERED)
    if not ctx.participation_active:
        return CheckResult(ok=False, reject=RejectCode.LEFT_CHALLENGE)
    if not ctx.challenge_active:
        return CheckResult(ok=False, reject=RejectCode.CHALLENGE_INACTIVE)
    if not ctx.challenge_started:
        return CheckResult(ok=False, reject=RejectCode.NOT_STARTED)
    if ctx.challenge_finished:
        return CheckResult(ok=False, reject=RejectCode.FINISHED)

    if meta.is_forwarded:
        return CheckResult(ok=False, reject=RejectCode.FORWARDED)
    if not (ctx.min_duration <= meta.duration <= ctx.max_duration):
        return CheckResult(ok=False, reject=RejectCode.BAD_DURATION)
    if ctx.duplicate_exists:
        return CheckResult(ok=False, reject=RejectCode.DUPLICATE)

    # Блокировки «дождись вердикта» больше нет: кружок зачитывается сразу,
    # а судья приходит потом. Участник никогда не заперт чужим молчанием.
    return CheckResult(ok=True, flags=collect_flags(meta, ctx))
