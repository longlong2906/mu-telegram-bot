import httpx
import pytest

from mu_bot.errors import BotError
from mu_bot.http import request_json
from mu_bot.telegram import Telegram

TOKEN = "123456:private-telegram-token"


def test_transient_read_retries_then_succeeds():
    calls, delays = [], []

    def handle(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) < 3 else 200, json={"events": []})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        body = request_json(
            client, "GET", "https://example.com", service="ESPN", sleep=delays.append
        )
    assert body == {"events": []} and len(calls) == 3 and delays == [1, 2]


def test_send_timeout_is_not_retried_and_does_not_leak_token(capsys):
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout(f"secret URL {request.url}", request=request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(BotError) as caught:
            Telegram(client, TOKEN, "123").send("test")
    assert len(calls) == 1
    assert TOKEN not in str(caught.value)
    assert TOKEN not in capsys.readouterr().err


def test_explicit_telegram_rate_limit_respects_retry_after():
    calls, delays = [], []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"parameters": {"retry_after": 2}})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        request_json(
            client,
            "POST",
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            service="Telegram",
            retry_safe=False,
            sleep=delays.append,
        )
    assert len(calls) == 2 and delays == [2]


@pytest.mark.parametrize("status", [400, 403, 500])
def test_send_errors_are_not_retried_or_logged(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"description": f"bad token {TOKEN}"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(BotError) as caught:
            Telegram(client, TOKEN, "123").send("test")
    assert len(calls) == 1 and TOKEN not in str(caught.value)


def test_chat_ids_only_returns_private_chats_without_consuming_updates():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {"message": {"chat": {"type": "private", "id": 123}}},
                    {"message": {"chat": {"type": "private", "id": 123}}},
                    {"message": {"chat": {"type": "group", "id": -456}}},
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert Telegram(client, TOKEN).private_chat_ids() == [123]
    assert b'"offset"' not in requests[0].content


def test_invalid_json_and_api_rejection_are_safe():
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=TOKEN))
    ) as client:
        with pytest.raises(BotError) as caught:
            Telegram(client, TOKEN, "123").send("test")
    assert TOKEN not in str(caught.value)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": False, "description": TOKEN})
        )
    ) as client:
        with pytest.raises(BotError) as caught:
            Telegram(client, TOKEN, "123").send("test")
    assert TOKEN not in str(caught.value)
