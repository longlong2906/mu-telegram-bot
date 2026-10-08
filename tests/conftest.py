from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mu_bot.errors import BotError, StateError
from mu_bot.models import Match
from mu_bot.state import State

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)


@pytest.fixture
def make_match():
    def factory(**changes):
        baseline = Match(
            id="401878773",
            league="eng.1",
            league_name="Premier League",
            kickoff=NOW + timedelta(hours=24),
            time_valid=True,
            home="Manchester United",
            away="Tottenham Hotspur",
            home_id="360",
            away_id="367",
            status="STATUS_SCHEDULED",
            state="pre",
            completed=False,
            venue="Old Trafford",
            url="https://www.espn.com/soccer/match/_/gameId/401878773",
        )
        return replace(baseline, **changes)

    return factory


class MemoryStore:
    def __init__(self, state=None, fail_on_save=None):
        self.text = state.dumps() if state else None
        self.saves = 0
        self.fail_on_save = fail_on_save

    def load(self):
        return State.loads(self.text) if self.text else None

    def save(self, state):
        self.saves += 1
        if self.saves == self.fail_on_save:
            raise StateError("State persistence failed")
        self.text = state.dumps()


class FakeProvider:
    def __init__(self, matches, details=None):
        self.items = matches
        self.detail_items = details or {}
        self.detail_calls = []

    def matches(self):
        return list(self.items)

    def details(self, match):
        self.detail_calls.append(match.id)
        return self.detail_items.get(match.id, match)


class FakeSender:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    def send(self, text):
        if self.fail:
            raise BotError("Telegram unavailable")
        self.messages.append(text)
