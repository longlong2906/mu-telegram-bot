import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from mu_bot.errors import BotError, StateError
from mu_bot.http import request_json
from mu_bot.models import Match, parse_datetime


@dataclass
class Entry:
    match: Match
    sent: set[str] = field(default_factory=set)
    announced_kickoff: str | None = None


@dataclass
class State:
    initialized_at: datetime
    matches: dict[str, Entry] = field(default_factory=dict)
    last_success_date: str | None = None

    @classmethod
    def start(cls, now: datetime, matches: list[Match]) -> "State":
        state = cls(now)
        for match in matches:
            state.matches[match.id] = Entry(match, {"result"} if match.finished else set())
        return state

    def dumps(self) -> str:
        return (
            json.dumps(
                {
                    "version": 1,
                    "initialized_at": self.initialized_at.isoformat(),
                    "last_success_date": self.last_success_date,
                    "matches": {
                        key: {
                            "match": entry.match.to_dict(),
                            "sent": sorted(entry.sent),
                            "announced_kickoff": entry.announced_kickoff,
                        }
                        for key, entry in sorted(self.matches.items())
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )

    @classmethod
    def loads(cls, text: str) -> "State":
        try:
            body = json.loads(text)
            if body["version"] != 1:
                raise ValueError("Unsupported state version")
            initialized_at = parse_datetime(body["initialized_at"])
            if initialized_at is None:
                raise ValueError("Missing initialization time")
            state = cls(initialized_at, last_success_date=body["last_success_date"])
            if state.last_success_date is not None:
                datetime.strptime(state.last_success_date, "%Y-%m-%d")
            for key, record in body["matches"].items():
                match = Match.from_dict(record["match"])
                if key != match.id or not match.official:
                    raise ValueError("Invalid match ID")
                sent = record["sent"]
                if not isinstance(sent, list) or not set(sent) <= {"24h", "1h", "result"}:
                    raise ValueError("Invalid notification flags")
                announced = record["announced_kickoff"]
                parse_datetime(announced)
                state.matches[key] = Entry(match, set(sent), announced)
            return state
        except (ValueError, KeyError, TypeError, AttributeError):
            raise StateError("Trạng thái lưu không hợp lệ; dừng để tránh gửi lại tin cũ.") from None


class StateStore(Protocol):
    def load(self) -> State | None: ...
    def save(self, state: State) -> None: ...


class LocalStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> State | None:
        try:
            return State.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError):
            raise StateError("Không đọc được file trạng thái local.") from None

    def save(self, state: State) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(state.dumps(), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            raise StateError("Không lưu được trạng thái local; dừng gửi tin.") from None


class GitHubStore:
    """Persist only non-sensitive state using Contents API with blob SHA concurrency checks."""

    def __init__(self, client: httpx.Client, repository: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
            raise StateError("Backend GitHub cần GITHUB_REPOSITORY và GITHUB_TOKEN hợp lệ.")
        self.client = client
        self.base_url = f"https://api.github.com/repos/{repository}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.branch = "bot-state"
        self.sha: str | None = None
        self.loaded = False

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        url = f"{self.base_url}/{path}" if path else self.base_url
        return request_json(
            self.client,
            method,
            url,
            headers=self.headers,
            service="GitHub",
            retry_safe=method == "GET",
            **kwargs,
        )

    def load(self) -> State | None:
        try:
            body = self._request(
                "GET", "contents/state.json", params={"ref": self.branch}, allow_missing=True
            )
            self.loaded = True
            if body is None:
                # Distinguish first initialization from a deleted file in an existing state branch.
                branch = self._request("GET", f"git/ref/heads/{self.branch}", allow_missing=True)
                if branch is not None:
                    raise StateError(
                        "Nhánh bot-state tồn tại nhưng thiếu state.json; cần khôi phục."
                    )
                return None
            self.sha = body["sha"]
            if body["encoding"] != "base64":
                raise ValueError("Unexpected encoding")
            return State.loads(base64.b64decode(body["content"]).decode("utf-8"))
        except StateError:
            raise
        except (BotError, KeyError, ValueError, TypeError):
            raise StateError("Không đọc được trạng thái GitHub; dừng gửi tin.") from None

    def save(self, state: State) -> None:
        if not self.loaded:
            raise StateError("Phải đọc trạng thái trước khi ghi.")
        try:
            if self.sha is None:
                branch = self._request("GET", f"git/ref/heads/{self.branch}", allow_missing=True)
                if branch is None:
                    repo = self._request("GET", "")
                    default = repo["default_branch"]
                    reference = self._request("GET", f"git/ref/heads/{default}")
                    parent_sha = reference["object"]["sha"]
                    parent = self._request("GET", f"git/commits/{parent_sha}")
                    blob = self._request(
                        "POST",
                        "git/blobs",
                        json={"content": state.dumps(), "encoding": "utf-8"},
                    )
                    tree = self._request(
                        "POST",
                        "git/trees",
                        json={
                            "base_tree": parent["tree"]["sha"],
                            "tree": [
                                {
                                    "path": "state.json",
                                    "mode": "100644",
                                    "type": "blob",
                                    "sha": blob["sha"],
                                }
                            ],
                        },
                    )
                    commit = self._request(
                        "POST",
                        "git/commits",
                        json={
                            "message": "Initialize bot notification state",
                            "tree": tree["sha"],
                            "parents": [parent_sha],
                            "author": {
                                "name": "github-actions[bot]",
                                "email": "41898282+github-actions[bot]@users.noreply.github.com",
                            },
                        },
                    )
                    # Publish a ref only AFTER its commit already contains state.json.
                    # A crash during initialization cannot expose an empty state branch.
                    self._request(
                        "POST",
                        "git/refs",
                        json={"ref": f"refs/heads/{self.branch}", "sha": commit["sha"]},
                    )
                    self.sha = blob["sha"]
                    return
            payload = {
                "message": "Update bot notification state",
                "branch": self.branch,
                "content": base64.b64encode(state.dumps().encode("utf-8")).decode("ascii"),
            }
            if self.sha is not None:
                payload["sha"] = self.sha
            body = self._request("PUT", "contents/state.json", json=payload)
            self.sha = body["content"]["sha"]
        except (BotError, KeyError, ValueError, TypeError):
            raise StateError("Không lưu được trạng thái GitHub; dừng gửi tin.") from None
