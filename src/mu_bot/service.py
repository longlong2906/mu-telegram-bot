from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from mu_bot.messages import remaining_text, reminder, result_message, schedule_change
from mu_bot.models import Match
from mu_bot.state import Entry, State, StateStore


class Provider(Protocol):
    def matches(self) -> list[Match]: ...
    def details(self, match: Match) -> Match: ...


class Sender(Protocol):
    def send(self, text: str) -> None: ...


@dataclass
class Report:
    matches: list[Match]
    messages: list[str]
    initialized: bool


def result_eligible(match: Match, entry: Entry, now: datetime) -> bool:
    return (
        match.finished
        and "result" not in entry.sent
        and match.kickoff is not None
        and now - timedelta(days=7) <= match.kickoff <= now
    )


def due_reminder(match: Match, entry: Entry, now: datetime) -> str | None:
    if (
        match.blocked
        or match.completed
        or match.state != "pre"
        or not match.time_valid
        or match.kickoff is None
    ):
        return None
    remaining = match.kickoff - now
    if timedelta(0) < remaining <= timedelta(hours=1):
        return "1h" if "1h" not in entry.sent else None
    if timedelta(hours=1) < remaining <= timedelta(hours=24):
        return "24h" if "24h" not in entry.sent else None
    return None


def check(
    provider: Provider,
    store: StateStore,
    sender: Sender | None,
    now: datetime,
    *,
    dry_run: bool = False,
) -> Report:
    state = store.load()
    before = state.dumps() if state else None
    matches = provider.matches()
    initialized = state is None
    if state is None:
        state = State.start(now, matches)
    else:
        # Recover pending matches that disappeared from the current-season schedule.
        known_ids = {match.id for match in matches}
        for key, entry in state.matches.items():
            previous = entry.match
            if (
                key not in known_ids
                and "result" not in entry.sent
                and not previous.blocked
                and previous.kickoff is not None
                and now - timedelta(days=7) <= previous.kickoff <= now
            ):
                matches.append(provider.details(previous))

    for match in matches:
        if match.id not in state.matches:
            state.matches[match.id] = Entry(match)
        else:
            entry = state.matches[match.id]
            if match.kickoff_key != entry.match.kickoff_key and "result" not in entry.sent:
                entry.sent.difference_update({"24h", "1h"})
            entry.match = match

    # Verify state persistence before any send, including the first-run historical baseline.
    def persist() -> None:
        nonlocal before
        serialized = state.dumps()
        if not dry_run and serialized != before:
            store.save(state)
            before = serialized

    persist()

    planned: list[str] = []
    for match in sorted(matches, key=lambda item: item.kickoff_key or ""):
        entry = state.matches[match.id]
        marks: set[str] = set()
        announced = False
        if result_eligible(match, entry, now):
            detailed = provider.details(match)
            entry.match = detailed
            if not detailed.finished or not detailed.has_score:
                continue
            match = detailed
            text = result_message(match)
            marks.add("result")
        else:
            due = due_reminder(match, entry, now)
            changed = (
                entry.announced_kickoff is not None
                and entry.announced_kickoff != match.kickoff_key
                and not match.blocked
                and not match.completed
                and match.state == "pre"
                and match.time_valid
                and match.kickoff is not None
                and match.kickoff > now
            )
            if changed:
                text = schedule_change(match) + f"\n⏳ Còn khoảng {remaining_text(match, now)}"
            elif due:
                text = reminder(match, now)
            else:
                continue
            if due:
                marks.add(due)
                if due == "1h":
                    marks.add("24h")
            announced = True
        planned.append(text)
        if not dry_run:
            if sender is None:
                raise ValueError("Real checks require a sender")
            sender.send(text)
        entry.sent.update(marks)
        if announced:
            entry.announced_kickoff = match.kickoff_key
        persist()

    state.last_success_date = now.date().isoformat()
    # Includes a once-per-UTC-day heartbeat even when there are no fixtures.
    persist()
    return Report(matches, planned, initialized)
