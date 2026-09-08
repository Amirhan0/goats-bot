"""Бэкап SQLite через VACUUM INTO — консистентный снимок без остановки бота."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

from bot.db.session import session_scope

logger = logging.getLogger(__name__)

MAX_UPLOAD_MB = 45


async def make_backup(backup_dir: Path, tz: ZoneInfo, keep: int) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz).strftime("%Y%m%d-%H%M")
    target = backup_dir / f"bot-{stamp}.db"

    async with session_scope() as session:
        # VACUUM INTO не принимает биндов — путь подставляется как литерал,
        # поэтому кавычки в имени экранируем.
        safe_path = str(target).replace("'", "''")
        await session.execute(text(f"VACUUM INTO '{safe_path}'"))

    rotate(backup_dir, keep)
    logger.info("Бэкап готов: %s (%.1f МБ)", target, size_mb(target))
    return target


def rotate(backup_dir: Path, keep: int) -> list[Path]:
    backups = sorted(backup_dir.glob("bot-*.db"), key=lambda p: p.name, reverse=True)
    removed: list[Path] = []
    for old in backups[keep:]:
        try:
            old.unlink()
            removed.append(old)
        except OSError:
            logger.warning("Не удалось удалить старый бэкап %s", old)
    return removed


def size_mb(path: Path) -> float:
    return path.stat().st_size / 1024 / 1024
