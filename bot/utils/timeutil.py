from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_local(moment: datetime, tz: ZoneInfo) -> datetime:
    return moment.astimezone(tz)


def fmt_time(moment: datetime, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).strftime("%H:%M")


def fmt_datetime(moment: datetime, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).strftime("%d.%m.%Y %H:%M")


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    match n % 10:
        case 1:
            return one
        case 2 | 3 | 4:
            return few
        case _:
            return many


def days_word(n: int) -> str:
    return plural_ru(n, "день", "дня", "дней")


def circles_word(n: int) -> str:
    return plural_ru(n, "кружок", "кружка", "кружков")


# Родительный падеж: «топ за август»
MONTHS_RU = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)


def month_name(month: int) -> str:
    return MONTHS_RU[month - 1]


# Родительный падеж для дат: «28 августа»
MONTHS_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

# «во вторник», «в среду» — предлог и падеж зависят от дня, поэтому список,
# а не склейка «в » + название.
WEEKDAYS_IN = (
    "в понедельник", "во вторник", "в среду", "в четверг",
    "в пятницу", "в субботу", "в воскресенье",
)


def local_today(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


def month_start_at(tz: ZoneInfo) -> datetime:
    """Полночь первого числа текущего месяца.

    Именно момент времени, а не дата: тренировки хранят start_at как
    datetime, и сравнение с date роняет запрос на приведении типов.
    """
    today = datetime.now(tz).date()
    return datetime.combine(today.replace(day=1), time.min, tzinfo=tz)


def weekday_in(moment: datetime, tz: ZoneInfo) -> str:
    return WEEKDAYS_IN[moment.astimezone(tz).weekday()]


def format_date_ru(day: date) -> str:
    """«1 сентября» — для дат, у которых нет времени."""
    return f"{day.day} {MONTHS_GEN[day.month - 1]}"


def format_day(moment: datetime, tz: ZoneInfo) -> str:
    """«28 августа»."""
    local = moment.astimezone(tz)
    return f"{local.day} {MONTHS_GEN[local.month - 1]}"


def format_day_with_weekday(moment: datetime, tz: ZoneInfo) -> str:
    """«пт, 28 августа»."""
    local = moment.astimezone(tz)
    return f"{WEEKDAYS_SHORT[local.weekday()]}, {format_day(moment, tz)}"
