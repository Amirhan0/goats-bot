"""Закрытие дня на границе суток и итоговый пост в беседу следом.

Индивидуальных уведомлений о прерванной серии нет: ночью будить всех
личками незачем. Вместо этого всё сводится в один пост дня, который читают
утром. Список тех, у кого серия прервалась, собирается прямо здесь.

Кружок зачитывается при приёме, поэтому «непросмотренная судьёй сдача»
закрывает день так же, как просмотренная. Пропуск — это день, за который
кружка не было вовсе.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.enums import AuditAction
from bot.repositories import audit as audit_repo
from bot.repositories import participations as participations_repo
from bot.repositories import submissions as submissions_repo
from bot.services import announce as announce_service
from bot.services import challenge as challenge_service
from bot.services import stats as stats_service
from bot.services.challenge_day import day_number

logger = logging.getLogger(__name__)


@dataclass
class CloseReport:
    day: int
    day_date: date
    done: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)
    top_name: str | None = None
    top_streak: int = 0

    @property
    def streaks_broken(self) -> int:
        return len(self.broken)


async def close_day(
    session: AsyncSession, settings: Settings, day_date: date
) -> CloseReport | None:
    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        logger.warning("Нет активного челленджа — закрытие дня пропущено")
        return None

    day = day_number(day_date, challenge.start_date)
    report = CloseReport(day=day, day_date=day_date)
    if day < 1:
        logger.info("День %s ещё до старта челленджа — закрывать нечего", day_date)
        return report

    for participation in await participations_repo.list_active(session, challenge.id):
        if participation.join_day > day:
            continue  # человек вступил позже — этот день ему не в минус

        name = participation.user.display_name
        approved = await submissions_repo.approved_days(session, participation.id)
        streak_before = participation.current_streak

        # Следующий день уже наступил — считаем серию относительно него.
        streak_after, _best = await stats_service.refresh_streaks(
            session, participation, day + 1
        )

        if day in approved:
            report.done.append(name)
        else:
            report.missed.append(name)
            if streak_before > 0 and streak_after == 0:
                report.broken.append(f"{name} ({streak_before})")

        if participation.current_streak > report.top_streak:
            report.top_streak = participation.current_streak
            report.top_name = name

    await audit_repo.log(
        session,
        actor_id=None,
        action=AuditAction.DAY_CLOSED,
        target_type="challenge",
        target_id=challenge.id,
        payload={
            "day": day,
            "date": day_date.isoformat(),
            "done": len(report.done),
            "missed": len(report.missed),
            "broken": len(report.broken),
        },
    )
    await session.commit()
    logger.info(
        "День %s (№%s) закрыт: сдали %s, пропустили %s, серий порвано %s",
        day_date,
        day,
        len(report.done),
        len(report.missed),
        len(report.broken),
    )
    return report


async def build_report(
    session: AsyncSession, settings: Settings, day_date: date
) -> CloseReport | None:
    """Тот же срез, но без побочных эффектов — для итогового поста.
    Список прерванных серий здесь не восстановить (серии уже обнулены при закрытии),
    поэтому пост дня собирается из отчёта close_day, а это — запасной путь."""
    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        return None

    day = day_number(day_date, challenge.start_date)
    report = CloseReport(day=day, day_date=day_date)
    if day < 1:
        return report

    for participation in await participations_repo.list_active(session, challenge.id):
        if participation.join_day > day:
            continue
        name = participation.user.display_name
        approved = await submissions_repo.approved_days(session, participation.id)

        if day in approved:
            report.done.append(name)
        else:
            report.missed.append(name)

        if participation.current_streak > report.top_streak:
            report.top_streak = participation.current_streak
            report.top_name = name

    return report


async def post_digest(
    bot: Bot,
    settings: Settings,
    report: CloseReport,
    month_top: list[str] | None = None,
    month: str = "",
    day_top: list[str] | None = None,
) -> None:
    """В посте дня имена без пингов: он выходит ночью, будить всех незачем."""
    text = texts.daily_digest(
        month=month,
        month_top=month_top,
        day_top=day_top,
        day=report.day,
        date_str=report.day_date.strftime("%d.%m.%Y"),
        done=[texts.esc(n) for n in report.done],
        missed=[texts.esc(n) for n in report.missed],
        broken=[texts.esc(n) for n in report.broken],
        top_name=report.top_name,
        top_streak=report.top_streak,
    )
    await announce_service.post_to_chat(
        bot, settings, text, disable_notification=True
    )
