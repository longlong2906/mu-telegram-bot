import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from mu_bot.errors import BotError
from mu_bot.espn import ESPN, parse_match, score
from mu_bot.messages import kickoff_text, result_message

FIXTURES = Path(__file__).parent / "fixtures"


def event_body():
    body = json.loads((FIXTURES / "espn_penalties.json").read_text())
    event = body["header"]
    event["league"] = {"slug": "eng.league_cup", "name": "League Cup"}
    return event


def test_realistic_penalty_fixture_and_home_away_order():
    event = event_body()
    # Reverse upstream ordering: homeAway, not array order, determines the score order.
    event["competitions"][0]["competitors"].reverse()
    match = parse_match(event)
    message = result_message(match)
    assert match.home == "Grimsby Town" and match.away == "Manchester United"
    assert "Grimsby Town 2–2 Manchester United" in message
    assert "12–11" in message and "thua" in message and "Sau luân lưu" in message


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"value": 0}, 0),
        ({"displayValue": "2"}, 2),
        ("0", 0),
        (3.0, 3),
        (None, None),
        (-1, None),
        (1.5, None),
        (True, None),
        ("nan", None),
        ("inf", None),
        ("bad", None),
    ],
)
def test_nullable_scores(value, expected):
    assert score(value) == expected


def test_schedule_score_object_and_unknown_time():
    event = event_body()
    competition = event["competitions"][0]
    competition["timeValid"] = False
    competition["competitors"][0]["score"] = {"value": 0.0, "displayValue": "0"}
    match = parse_match(event)
    assert match.home_score == 0 and not match.time_valid


def test_timezone_rolls_over_to_next_day(make_match):
    match = make_match()
    assert "01:00 ngày 10/10/2026" in kickoff_text(match)
    assert "giờ Việt Nam" in kickoff_text(match)


@pytest.mark.parametrize(
    "home,away,mu_at_home,outcome",
    [(3, 1, True, "thắng"), (1, 3, True, "thua"), (0, 0, True, "hòa"), (1, 3, False, "thắng")],
)
def test_result_outcomes_without_winner_flags(make_match, home, away, mu_at_home, outcome):
    match = make_match(home_score=home, away_score=away)
    if not mu_at_home:
        match = replace(match, home_id="367", away_id="360")
    assert outcome in result_message(match)


def test_extra_time_and_missing_shootout_winner(make_match):
    match = make_match(home_score=1, away_score=1, status="STATUS_FINAL_AET")
    assert "Sau hiệp phụ" in result_message(match)
    match = replace(match, status="STATUS_FINAL_PEN")
    assert "hòa" not in result_message(match)
    assert "chưa cung cấp tỷ số luân lưu" in result_message(match)


def test_fetch_merges_official_events_with_results_precedence():
    result = event_body()
    future = json.loads(json.dumps(result))
    future["competitions"][0]["status"]["type"]["completed"] = False
    friendly = json.loads(json.dumps(result))
    friendly["id"] = "friendly"
    friendly["league"]["slug"] = "club.friendly"
    unrelated = json.loads(json.dumps(result))
    unrelated["id"] = "another-team"
    unrelated["competitions"][0]["competitors"][1]["team"]["id"] = "999"

    def handle(request):
        events = [future, friendly, unrelated] if request.url.params.get("fixture") else [result]
        return httpx.Response(200, json={"events": events})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        matches = ESPN(client).matches()
    assert len(matches) == 1
    assert matches[0].finished


def test_detail_endpoint_supplies_penalties(make_match):
    body = json.loads((FIXTURES / "espn_penalties.json").read_text())
    original = make_match(id="756229", league="eng.league_cup", home_id="386", away_id="360")
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as c:
        match = ESPN(c).details(original)
    assert match.home_penalties == 12 and match.away_penalties == 11


@pytest.mark.parametrize("malformation", [{}, {"events": None}, {"events": [{"id": "broken"}]}])
def test_schema_errors_fail_visibly(malformation):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=malformation))
    ) as client:
        with pytest.raises(BotError, match="ESPN"):
            ESPN(client).matches()


def test_detail_cannot_substitute_another_event(make_match):
    body = json.loads((FIXTURES / "espn_penalties.json").read_text())
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(BotError, match="không khớp"):
            ESPN(client).details(make_match())
