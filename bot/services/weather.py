"""Погода на час тренировки — Open-Meteo.

Бесплатный API без ключа и регистрации, поэтому не тащим ни токенов,
ни новых зависимостей: aiohttp и так приходит вместе с aiogram.

Сеть может не ответить, и это не повод ронять создание тренировки:
при любой ошибке возвращаем None, а поле «погода» остаётся пустым —
админ впишет руками.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

logger = logging.getLogger(__name__)

API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SEC = 8
# Прогноз дальше двух недель Open-Meteo не отдаёт.
MAX_FORECAST_DAYS = 16

# Коды WMO → человеческое описание.
WMO: dict[int, str] = {
    0: "ясно",
    1: "малооблачно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "туман с изморозью",
    51: "морось",
    53: "морось",
    55: "сильная морось",
    56: "ледяная морось",
    57: "ледяная морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "ледяной дождь",
    67: "ледяной дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снег",
    77: "снежная крупа",
    80: "кратковременный дождь",
    81: "ливень",
    82: "сильный ливень",
    85: "снегопад",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с градом",
    99: "гроза с градом",
}

# Коды, при которых осадки уже в описании — «возможен дождь» будет лишним.
_WET = frozenset(range(51, 68)) | frozenset(range(71, 87)) | {95, 96, 99}


@dataclass(frozen=True, slots=True)
class Forecast:
    temperature: float
    code: int
    precipitation: int  # вероятность осадков, %

    def describe(self) -> str:
        """«около 25°C, возможен дождь» — в том же виде, как пишет клуб."""
        parts = [f"около {round(self.temperature)}°C"]
        condition = WMO.get(self.code)

        if self.code in _WET:
            parts.append(condition or "осадки")
        elif self.precipitation >= 40:
            parts.append("возможен дождь")
        elif condition and self.code != 0:
            parts.append(condition)

        return ", ".join(parts)


def _pick_hour(payload: dict, target: datetime, tz: ZoneInfo) -> Forecast | None:
    """Open-Meteo отдаёт почасовой ряд в локальном времени — ищем нужный час."""
    hourly = payload.get("hourly") or {}
    stamps: list[str] = hourly.get("time") or []
    if not stamps:
        return None

    wanted = target.astimezone(tz).strftime("%Y-%m-%dT%H:00")
    try:
        index = stamps.index(wanted)
    except ValueError:
        logger.info("Нет прогноза на %s — слишком далеко или уже прошло", wanted)
        return None

    def at(key: str, default: float = 0.0) -> float:
        values = hourly.get(key) or []
        value = values[index] if index < len(values) else None
        return default if value is None else value

    return Forecast(
        temperature=at("temperature_2m"),
        code=int(at("weather_code")),
        precipitation=int(at("precipitation_probability")),
    )


async def fetch(target: datetime, tz: ZoneInfo, lat: float, lon: float) -> Forecast | None:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "timezone": str(tz),
        "forecast_days": MAX_FORECAST_DAYS,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.get(API_URL, params=params) as response:
                response.raise_for_status()
                payload = await response.json()
    except Exception:  # noqa: BLE001 — прогноз не критичен, поле просто останется пустым
        logger.warning("Не удалось получить прогноз погоды", exc_info=True)
        return None

    return _pick_hour(payload, target, tz)


async def describe(target: datetime, tz: ZoneInfo, lat: float, lon: float) -> str:
    forecast = await fetch(target, tz, lat, lon)
    return forecast.describe() if forecast else ""
