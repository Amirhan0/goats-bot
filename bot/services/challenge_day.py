"""Календарь челленджа. Чистые функции, без БД и без aiogram.

День D — это окно [D boundary:00, D+1 boundary:00) по таймзоне челленджа.
При boundary = 0 это обычные календарные сутки: приём до полуночи.
При ненулевом boundary сутки сдвинуты и появляется ночная фора — например,
при 4 кружок, присланный в 01:30, засчитывается за прошедший день.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_BOUNDARY_HOUR = 0


def local_day_for(moment: datetime, tz: ZoneInfo, boundary_hour: int = DEFAULT_BOUNDARY_HOUR) -> date:
    """Календарная дата челленджа, которой принадлежит момент времени."""
    if moment.tzinfo is None:
        raise ValueError("нужен aware datetime")
    local = moment.astimezone(tz)
    if local.hour < boundary_hour:
        local -= timedelta(days=1)
    return local.date()


def day_window(
    day: date, tz: ZoneInfo, boundary_hour: int = DEFAULT_BOUNDARY_HOUR
) -> tuple[datetime, datetime]:
    """Границы дня в UTC: [начало, конец). Конец = граница следующих суток."""
    start = datetime.combine(day, time(hour=boundary_hour), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time(hour=boundary_hour), tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def day_end(day: date, tz: ZoneInfo, boundary_hour: int = DEFAULT_BOUNDARY_HOUR) -> datetime:
    return day_window(day, tz, boundary_hour)[1]


def seconds_to_day_end(
    moment: datetime, tz: ZoneInfo, boundary_hour: int = DEFAULT_BOUNDARY_HOUR
) -> int:
    day = local_day_for(moment, tz, boundary_hour)
    return int((day_end(day, tz, boundary_hour) - moment).total_seconds())


def month_start(day: date) -> date:
    """Первое число месяца, которому принадлежит день челленджа.
    Месяц берётся по календарной дате дня, а не по времени отправки:
    кружок в 01:30 первого числа относится к прошлому месяцу."""
    return day.replace(day=1)


def day_number(day: date, start_date: date) -> int:
    """1 = первый день челленджа. Может быть <= 0, если челлендж ещё не начался."""
    return (day - start_date).days + 1


def date_for_day(number: int, start_date: date) -> date:
    return start_date + timedelta(days=number - 1)


def current_day_number(
    moment: datetime,
    start_date: date,
    tz: ZoneInfo,
    boundary_hour: int = DEFAULT_BOUNDARY_HOUR,
) -> int:
    return day_number(local_day_for(moment, tz, boundary_hour), start_date)


def is_challenge_running(
    moment: datetime,
    start_date: date,
    end_date: date | None,
    tz: ZoneInfo,
    boundary_hour: int = DEFAULT_BOUNDARY_HOUR,
) -> bool:
    day = local_day_for(moment, tz, boundary_hour)
    if day < start_date:
        return False
    return end_date is None or day <= end_date
