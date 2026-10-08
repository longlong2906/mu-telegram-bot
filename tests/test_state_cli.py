import base64
import json

import httpx
import pytest
from conftest import NOW, FakeProvider, FakeSender, MemoryStore

from mu_bot.cli import main
from mu_bot.errors import StateError
from mu_bot.service import check
from mu_bot.state import GitHubStore, LocalStore, State


def test_local_state_roundtrip_and_dry_run_is_read_only(tmp_path, make_match):
    path = tmp_path / "state" / "state.json"
    store = LocalStore(path)
    assert store.load() is None
    check(FakeProvider([make_match()]), store, FakeSender(), NOW, dry_run=True)
    assert not path.exists()
    check(FakeProvider([make_match()]), store, FakeSender(), NOW)
    before = path.read_bytes()
    check(FakeProvider([make_match()]), store, None, NOW, dry_run=True)
    assert before == path.read_bytes()
    assert "24h" in store.load().matches[make_match().id].sent


@pytest.mark.parametrize(
    "text", ["not json", "{}", '{"version": 2}', '{"version": 1, "initialized_at": "no-date"}']
)
def test_bad_state_never_silently_resets(text):
    with pytest.raises(StateError):
        State.loads(text)


def test_github_first_save_publishes_branch_after_state_commit():
    requests = []
    state = State(NOW)

    def handle(request):
        requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.endswith(("state.json", "heads/bot-state")):
            return httpx.Response(404)
        if path == "/repos/owner/repo":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("heads/main"):
            return httpx.Response(200, json={"object": {"sha": "main-sha"}})
        if path.endswith("git/commits/main-sha"):
            return httpx.Response(200, json={"tree": {"sha": "main-tree"}})
        if path.endswith("git/blobs"):
            payload = json.loads(request.content)
            assert State.loads(payload["content"]).initialized_at == NOW
            assert "TELEGRAM" not in payload["content"]
            return httpx.Response(201, json={"sha": "state-blob"})
        if path.endswith("git/trees"):
            assert json.loads(request.content)["tree"][0]["sha"] == "state-blob"
            return httpx.Response(201, json={"sha": "state-tree"})
        if path.endswith("git/commits"):
            assert json.loads(request.content)["tree"] == "state-tree"
            return httpx.Response(201, json={"sha": "state-commit"})
        if path.endswith("git/refs"):
            assert json.loads(request.content)["sha"] == "state-commit"
            return httpx.Response(201, json={"ref": "refs/heads/bot-state"})
        raise AssertionError(f"Unexpected request: {request.method} {path}")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        store = GitHubStore(client, "owner/repo", "secret-github-token")
        assert store.load() is None
        store.save(state)
        assert store.sha == "state-blob"
    assert requests[-1].url.path.endswith("git/refs")


def test_github_existing_state_uses_blob_sha():
    state = State(NOW)
    stored = {
        "sha": "old-sha",
        "encoding": "base64",
        "content": base64.b64encode(state.dumps().encode()).decode(),
    }

    def handle(request):
        if request.method == "GET":
            assert request.url.params["ref"] == "bot-state"
            return httpx.Response(200, json=stored)
        payload = json.loads(request.content)
        assert payload["sha"] == "old-sha" and payload["branch"] == "bot-state"
        return httpx.Response(200, json={"content": {"sha": "new-sha"}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        store = GitHubStore(client, "owner/repo", "secret-github-token")
        loaded = store.load()
        assert loaded.initialized_at == NOW
        store.save(loaded)
        assert store.sha == "new-sha"


def test_deleted_github_state_requires_recovery():
    def handle(request):
        if request.url.path.endswith("state.json"):
            return httpx.Response(404)
        return httpx.Response(200, json={"object": {"sha": "existing-state-branch"}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(StateError, match="khôi phục"):
            GitHubStore(client, "owner/repo", "token").load()


def test_github_auth_error_redacted():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={"message": "secret-github-token"})
        )
    ) as client:
        with pytest.raises(StateError) as caught:
            GitHubStore(client, "owner/repo", "secret-github-token").load()
    assert "secret-github-token" not in str(caught.value)


def test_github_conflict_stops_without_retry():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(409)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        store = GitHubStore(client, "owner/repo", "token")
        store.loaded, store.sha = True, "old-sha"
        with pytest.raises(StateError):
            store.save(State(NOW))
    assert len(calls) == 1


def test_cli_missing_credentials_are_safe(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert main(["check"]) == 1
    assert "TELEGRAM_CHAT_ID" in capsys.readouterr().err
    assert main(["chat-id"]) == 1
    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().err


def test_cli_dry_run_without_credentials_displays_vietnamese(monkeypatch, capsys, make_match):
    import mu_bot.cli as cli

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    provider = FakeProvider([make_match()])
    store = MemoryStore()
    monkeypatch.setattr(cli, "ESPN", lambda client: provider)
    monkeypatch.setattr(cli, "make_store", lambda client: store)
    assert main(["check", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "DRY-RUN" in output and "trận chính thức" in output
    assert store.saves == 0
