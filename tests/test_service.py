from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import NOW, FakeProvider, FakeSender, MemoryStore

from mu_bot.errors import BotError, StateError
from mu_bot.service import check
from mu_bot.state import State


@pytest.mark.parametrize(
    "seconds,expected",
    [(86401, None), (86400, "24h"), (3601, "24h"), (3600, "1h"), (1, "1h"), (0, None), (-60, None)],
)
def test_reminder_boundaries(make_match, seconds, expected):
    match = make_match(kickoff=NOW + timedelta(seconds=seconds))
    store, sender = MemoryStore(), FakeSender()
    check(FakeProvider([match]), store, sender, NOW)
    assert len(sender.messages) == (1 if expected else 0)
    sent = store.load().matches[match.id].sent
    if expected:
        assert expected in sent
    if expected == "1h":
        assert "24h" in sent


def test_delayed_runs_send_actual_remaining_once(make_match):
    match = make_match(kickoff=NOW + timedelta(hours=20, minutes=30))
    store, sender = MemoryStore(), FakeSender()
    provider = FakeProvider([match])
    check(provider, store, sender, NOW)
    check(provider, store, sender, NOW + timedelta(minutes=5))
    assert len(sender.messages) == 1
    assert "20 giờ 30 phút" in sender.messages[0]
    check(provider, store, sender, match.kickoff - timedelta(minutes=50))
    assert len(sender.messages) == 2
    check(provider, store, sender, match.kickoff)
    assert len(sender.messages) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"time_valid": False},
        {"kickoff": None},
        {"status": "STATUS_POSTPONED"},
        {"status": "STATUS_CANCELED"},
        {"status": "STATUS_ABANDONED"},
        {"status": "STATUS_DELAYED"},
        {"state": "in", "status": "STATUS_IN_PROGRESS"},
    ],
)
def test_unsafe_schedules_are_not_announced(make_match, changes):
    sender = FakeSender()
    check(FakeProvider([make_match(**changes)]), MemoryStore(), sender, NOW)
    assert sender.messages == []


def test_first_run_ignores_completed_results(make_match):
    finished = make_match(
        kickoff=NOW - timedelta(hours=3),
        state="post",
        status="STATUS_FULL_TIME",
        completed=True,
        home_score=0,
        away_score=0,
    )
    provider, sender, store = FakeProvider([finished]), FakeSender(), MemoryStore()
    check(provider, store, sender, NOW)
    check(provider, store, sender, NOW + timedelta(minutes=5))
    assert not sender.messages
    assert not provider.detail_calls
    assert "result" in store.load().matches[finished.id].sent


def test_started_before_initialization_still_gets_result(make_match):
    active = make_match(kickoff=NOW - timedelta(hours=1), state="in", status="STATUS_IN_PROGRESS")
    finished = replace(
        active, completed=True, state="post", status="STATUS_FULL_TIME", home_score=0, away_score=0
    )
    store, sender = MemoryStore(), FakeSender()
    check(FakeProvider([active]), store, sender, NOW)
    check(FakeProvider([finished]), store, sender, NOW + timedelta(hours=1))
    check(FakeProvider([finished]), store, sender, NOW + timedelta(hours=1, minutes=5))
    assert len(sender.messages) == 1
    assert "0–0" in sender.messages[0]
    assert "hòa" in sender.messages[0]


@pytest.mark.parametrize("age,expected", [(timedelta(days=7), 1), (timedelta(days=8), 0)])
def test_results_backfill_has_seven_day_limit(make_match, age, expected):
    match = make_match(
        kickoff=NOW - age,
        state="post",
        completed=True,
        status="STATUS_FULL_TIME",
        home_score=2,
        away_score=1,
    )
    store = MemoryStore(State(NOW - timedelta(days=9)))
    sender = FakeSender()
    check(FakeProvider([match]), store, sender, NOW)
    assert len(sender.messages) == expected


@pytest.mark.parametrize("missing_field", ["home_score", "away_score"])
def test_missing_result_score_waits_for_later(make_match, missing_field):
    match = make_match(
        kickoff=NOW - timedelta(hours=3),
        state="post",
        completed=True,
        status="STATUS_FULL_TIME",
        home_score=1,
        away_score=0,
    )
    missing = replace(match, **{missing_field: None})
    store, sender = MemoryStore(State(NOW - timedelta(days=1))), FakeSender()
    check(FakeProvider([match], {match.id: missing}), store, sender, NOW)
    assert not sender.messages
    assert "result" not in store.load().matches[match.id].sent
    check(FakeProvider([match]), store, sender, NOW + timedelta(minutes=5))
    assert len(sender.messages) == 1


def test_detail_must_confirm_completion(make_match):
    final = make_match(
        kickoff=NOW - timedelta(hours=3),
        completed=True,
        state="post",
        status="STATUS_FULL_TIME",
        home_score=1,
        away_score=0,
    )
    active = replace(final, state="in", completed=False)
    sender = FakeSender()
    check(
        FakeProvider([final], {final.id: active}),
        MemoryStore(State(NOW - timedelta(days=1))),
        sender,
        NOW,
    )
    assert not sender.messages


def test_pending_match_disappears_across_season(make_match):
    active = make_match(kickoff=NOW - timedelta(hours=1), state="in", status="STATUS_IN_PROGRESS")
    store, sender = MemoryStore(), FakeSender()
    check(FakeProvider([active]), store, sender, NOW)
    final = replace(
        active, state="post", completed=True, status="STATUS_FULL_TIME", home_score=2, away_score=0
    )
    check(FakeProvider([], {active.id: final}), store, sender, NOW + timedelta(hours=2))
    assert len(sender.messages) == 1


def test_schedule_change_announced_once_and_rearms_reminders(make_match):
    original = make_match(kickoff=NOW + timedelta(hours=20))
    store, sender = MemoryStore(), FakeSender()
    check(FakeProvider([original]), store, sender, NOW)
    changed = replace(original, kickoff=NOW + timedelta(hours=48))
    check(FakeProvider([changed]), store, sender, NOW + timedelta(minutes=5))
    check(FakeProvider([changed]), store, sender, NOW + timedelta(minutes=10))
    assert len(sender.messages) == 2
    assert "Cập nhật giờ bóng lăn" in sender.messages[1]
    check(FakeProvider([changed]), store, sender, NOW + timedelta(hours=24))
    assert len(sender.messages) == 3


def test_schedule_change_within_hour_combines_reminder(make_match):
    original = make_match(kickoff=NOW + timedelta(hours=20))
    store, sender = MemoryStore(), FakeSender()
    check(FakeProvider([original]), store, sender, NOW)
    changed = replace(original, kickoff=NOW + timedelta(minutes=30))
    check(FakeProvider([changed]), store, sender, NOW + timedelta(minutes=5))
    check(FakeProvider([changed]), store, sender, NOW + timedelta(minutes=10))
    assert len(sender.messages) == 2
    assert store.load().matches[changed.id].sent >= {"24h", "1h"}


def test_dry_run_never_sends_or_persists(make_match):
    match = make_match()
    store, sender = MemoryStore(), FakeSender()
    report = check(FakeProvider([match]), store, sender, NOW, dry_run=True)
    assert len(report.messages) == 1
    assert store.saves == 0 and store.text is None and not sender.messages


def test_state_failure_prevents_first_send(make_match):
    sender = FakeSender()
    with pytest.raises(StateError):
        check(FakeProvider([make_match()]), MemoryStore(fail_on_save=1), sender, NOW)
    assert not sender.messages


def test_save_failure_after_send_stops_next_send(make_match):
    first = make_match(kickoff=NOW + timedelta(hours=10))
    second = make_match(id="second", kickoff=NOW + timedelta(hours=20))
    sender = FakeSender()
    with pytest.raises(StateError):
        check(FakeProvider([first, second]), MemoryStore(fail_on_save=2), sender, NOW)
    assert len(sender.messages) == 1


def test_failed_telegram_send_does_not_mark_sent(make_match):
    store = MemoryStore()
    with pytest.raises(BotError):
        check(FakeProvider([make_match()]), store, FakeSender(fail=True), NOW)
    assert not store.load().matches[make_match().id].sent


def test_daily_heartbeat_and_no_per_check_writes():
    store = MemoryStore()
    check(FakeProvider([]), store, FakeSender(), NOW)
    previous = store.saves
    check(FakeProvider([]), store, FakeSender(), NOW + timedelta(minutes=5))
    assert store.saves == previous
    check(FakeProvider([]), store, FakeSender(), NOW + timedelta(days=1))
    assert store.saves == previous + 1
    assert store.load().last_success_date == "2026-10-09"
