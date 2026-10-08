from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

TEAM_ID = "360"
BLOCKED_STATUSES = frozenset(
    {
        "STATUS_POSTPONED",
        "STATUS_CANCELED",
        "STATUS_CANCELLED",
        "STATUS_ABANDONED",
        "STATUS_SUSPENDED",
        "STATUS_DELAYED",
    }
)


def parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Expected timezone-aware date")
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class Match:
    id: str
    league: str
    league_name: str
    kickoff: datetime | None
    time_valid: bool
    home: str
    away: str
    home_id: str
    away_id: str
    status: str
    state: str
    completed: bool
    venue: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    home_penalties: int | None = None
    away_penalties: int | None = None
    home_winner: bool = False
    away_winner: bool = False
    url: str | None = None

    @property
    def official(self) -> bool:
        return TEAM_ID in (self.home_id, self.away_id) and "friendly" not in self.league.casefold()

    @property
    def blocked(self) -> bool:
        return self.status in BLOCKED_STATUSES

    @property
    def finished(self) -> bool:
        return not self.blocked and self.completed and self.state == "post"

    @property
    def has_score(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    @property
    def kickoff_key(self) -> str | None:
        return self.kickoff.isoformat() if self.kickoff else None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["kickoff"] = self.kickoff_key
        return result

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> "Match":
        data = dict(body)
        data["kickoff"] = parse_datetime(data["kickoff"])
        result = cls(**data)
        for name in (
            "id",
            "league",
            "league_name",
            "home",
            "away",
            "home_id",
            "away_id",
            "status",
            "state",
        ):
            if not isinstance(getattr(result, name), str):
                raise ValueError("Invalid match field")
        for name in ("time_valid", "completed", "home_winner", "away_winner"):
            if type(getattr(result, name)) is not bool:
                raise ValueError("Invalid flag")
        for name in ("home_score", "away_score", "home_penalties", "away_penalties"):
            value = getattr(result, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Invalid score")
        return result
