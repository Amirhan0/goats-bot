"""Расписание должно жить в зоне челленджа, а не в зоне сервера.

Регрессия из боя: сервер в UTC, готовый CronTrigger брал системную зону,
и утренний пост уходил в 14:00 по Алматы вместо 09:00.
"""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger

from bot.scheduler.setup import build_scheduler


def test_every_cron_job_uses_challenge_timezone(settings) -> None:
    scheduler = build_scheduler(bot=None, settings=settings)
    crons = [j for j in scheduler.get_jobs() if isinstance(j.trigger, CronTrigger)]

    assert crons, "кроновых задач нет — тест бесполезен"
    for job in crons:
        assert str(job.trigger.timezone) == settings.timezone, (
            f"задача {job.id} висит в зоне {job.trigger.timezone}"
        )


def test_morning_post_fires_at_nine_local(settings) -> None:
    scheduler = build_scheduler(bot=None, settings=settings)
    trigger = scheduler.get_job("morning_post").trigger

    fields = {f.name: str(f) for f in trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("9", "0")


def test_day_close_follows_boundary_setting(settings) -> None:
    scheduler = build_scheduler(bot=None, settings=settings)
    fields = {f.name: str(f) for f in scheduler.get_job("close_day").trigger.fields}

    assert fields["hour"] == str(settings.day_boundary_hour)
