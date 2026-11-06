"""명시 단발 일정은 승인된 날짜/scope에만 적용되고 기본 운영은 유지한다."""

from datetime import timedelta

import pytest

from tests.newsletter.test_newsletter import DAY, context, inputs
from xfolio.newsletter.edition import (
    AcceptanceSchedule,
    NewsletterError,
    at,
    build_morning,
    check_send,
    schedule_times,
)


def test_acceptance_schedule_does_not_change_default_or_other_recipients():
    scope = "self_acceptance_test"
    schedule = AcceptanceSchedule(
        target_date=DAY,
        recipient_scope=scope,
        frozen_at=at(DAY, 7, 50),
        send_at=at(DAY, 9),
        deadline=at(DAY, 9, 1),
    )
    assert schedule_times(DAY, "self") == (at(DAY, 7, 50), at(DAY, 8), at(DAY, 8, 10))
    with pytest.raises(NewsletterError):
        schedule_times(DAY, "self", schedule)
    with pytest.raises(NewsletterError):
        schedule_times(DAY + timedelta(days=1), scope, schedule)
    edition = build_morning(
        inputs(live=True, recipient_scope=scope), now=at(DAY, 8, 55), schedule=schedule
    )
    assert edition.status == "ready"
    for minute, expected in [(0, True), (1, False)]:
        now = at(DAY, 9, minute)
        ctx = context(
            now=now,
            recipient_scope=scope,
            allowed_recipient_scopes=(scope,),
            calendar_checked_at=now,
            budget=context().budget.model_copy(update={"checked_at": now}),
        )
        assert check_send(edition, ctx, schedule=schedule).can_send is expected
    assert (
        "outside_send_window"
        in check_send(
            edition,
            context(recipient_scope=scope, allowed_recipient_scopes=(scope,)),
            schedule=schedule,
        ).reasons
    )
