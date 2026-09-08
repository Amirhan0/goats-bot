"""Поздняя отмена: минус в месячном счёте, но серия цела."""

from __future__ import annotations

from datetime import date

from bot.db.enums import SubmissionStatus
from bot.repositories import submissions as submissions_repo
from bot.services import stats as stats_service
from tests.conftest import make_participant, make_submission

SEPT = date(2026, 9, 1)


async def test_revoked_day_still_counts_for_streak(session, challenge):
    participation = await make_participant(session, challenge, 950)
    for day in (1, 2, 3):
        await make_submission(session, participation, day)

    revoked = await submissions_repo.get(session, 1)
    revoked.status = SubmissionStatus.REVOKED
    await session.commit()

    days = await submissions_repo.approved_days(session, participation.id)
    assert days == {1, 2, 3}  # день остался закрытым

    stats = await stats_service.build_user_stats(session, participation, 3, SEPT)
    assert stats.current_streak == 3
    assert stats.circles_month == 2  # но кружок ушёл из зачёта


async def test_rejected_day_does_not_count(session, challenge):
    """Отмена внутри того же дня — обычный незачёт, день не закрыт."""
    participation = await make_participant(session, challenge, 951)
    submission = await make_submission(session, participation, 1)
    submission.status = SubmissionStatus.REJECTED
    await session.commit()

    assert await submissions_repo.approved_days(session, participation.id) == set()
    assert await submissions_repo.count_approved(session, participation.id) == 0


async def test_undo_has_no_time_limit(session, settings, bot, challenge):
    """Судья снимает свою отмену и через неделю: окна на 15 минут больше нет.

    Кружок зачитывается автоматически, решение судьи — это только отмена
    зачёта. Заметить ошибку в ней можно сильно позже, и человек не должен
    оставаться без зачёта из-за таймера.
    """
    from datetime import timedelta

    from bot.services import moderation as moderation_service
    from bot.utils.timeutil import now_utc
    from tests.conftest import make_judge

    participation = await make_participant(session, challenge, 952)
    submission = await make_submission(session, participation, 1)
    judge = await make_judge(session, 901)

    week_ago = now_utc() - timedelta(days=7)
    submission.status = SubmissionStatus.REVOKED
    submission.judge_id = judge.id
    submission.judged_at = week_ago
    submission.reviewed_at = week_ago
    await session.commit()

    result = await moderation_service.undo(
        session, bot, settings, submission_id=submission.id, actor=judge
    )

    assert result.ok, result.message
    restored = await submissions_repo.get(session, submission.id)
    assert restored.status == SubmissionStatus.APPROVED
