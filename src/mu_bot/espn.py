from typing import Any

import httpx

from mu_bot.errors import BotError
from mu_bot.http import request_json
from mu_bot.models import Match, parse_datetime

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"


def score(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("value", value.get("displayValue"))
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        return int(number) if number >= 0 and number.is_integer() else None
    except (ValueError, TypeError, OverflowError):
        return None


def parse_match(event: dict[str, Any]) -> Match:
    try:
        competition = event["competitions"][0]
        teams = {item["homeAway"]: item for item in competition["competitors"]}
        home, away = teams["home"], teams["away"]
        status = competition["status"]["type"]
        league = event["league"]
        link = next(
            (
                item["href"]
                for item in event.get("links", [])
                if "summary" in item.get("rel", []) and "desktop" in item.get("rel", [])
            ),
            None,
        )
        if link and not link.startswith("https://www.espn.com/"):
            link = None
        result = Match(
            id=str(event["id"]),
            league=league["slug"],
            league_name=league["name"],
            kickoff=parse_datetime(competition.get("date", event.get("date"))),
            time_valid=event.get("timeValid", competition.get("timeValid")) is True,
            home=home["team"]["displayName"],
            away=away["team"]["displayName"],
            home_id=str(home["team"]["id"]),
            away_id=str(away["team"]["id"]),
            status=status["name"],
            state=status["state"],
            completed=status.get("completed") is True,
            venue=competition.get("venue", {}).get("fullName"),
            home_score=score(home.get("score")),
            away_score=score(away.get("score")),
            home_penalties=score(home.get("shootoutScore")),
            away_penalties=score(away.get("shootoutScore")),
            home_winner=home.get("winner") is True,
            away_winner=away.get("winner") is True,
            url=link,
        )
        # Validate types as well as presence, so a changed upstream schema fails visibly.
        return Match.from_dict(result.to_dict())
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        raise BotError("ESPN: cấu trúc dữ liệu trận đấu đã thay đổi hoặc không hợp lệ.") from None


class ESPN:
    def __init__(self, client: httpx.Client):
        self.client = client

    def matches(self) -> list[Match]:
        merged: dict[str, Match] = {}
        for suffix in ("?fixture=true", ""):
            body = request_json(
                self.client, "GET", f"{BASE_URL}/all/teams/360/schedule{suffix}", service="ESPN"
            )
            if body is None or not isinstance(body.get("events"), list):
                raise BotError("ESPN: phản hồi thiếu danh sách trận đấu.")
            for event in body["events"]:
                match = parse_match(event)
                if match.official:
                    # The results feed is read last and wins if a match appears in both feeds.
                    merged[match.id] = match
        return sorted(merged.values(), key=lambda match: match.kickoff_key or "")

    def details(self, match: Match) -> Match:
        body = request_json(
            self.client,
            "GET",
            f"{BASE_URL}/{match.league}/summary",
            service="ESPN",
            params={"event": match.id},
        )
        try:
            header = body["header"]
            if str(header["id"]) != match.id:
                raise ValueError("Unexpected event")
            event = dict(header)
            event["league"] = {"slug": match.league, "name": match.league_name}
            result = parse_match(event)
            if (result.home_id, result.away_id) != (match.home_id, match.away_id):
                raise ValueError("Unexpected teams")
            return result
        except (KeyError, TypeError, ValueError):
            raise BotError("ESPN: dữ liệu chi tiết không khớp trận đấu.") from None
