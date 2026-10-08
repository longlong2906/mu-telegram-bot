from typing import Any

import httpx

from mu_bot.errors import BotError
from mu_bot.http import request_json


class Telegram:
    def __init__(self, client: httpx.Client, token: str, chat_id: str = ""):
        if not token:
            raise BotError("Thiếu TELEGRAM_BOT_TOKEN.")
        self.client = client
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id

    def _call(self, method: str, **kwargs: Any) -> Any:
        body = request_json(
            self.client,
            "POST",
            f"{self.base_url}/{method}",
            service="Telegram",
            retry_safe=method == "getUpdates",
            **kwargs,
        )
        if body is None or body.get("ok") is not True:
            raise BotError("Telegram: yêu cầu bị từ chối.")
        return body.get("result")

    def send(self, text: str) -> None:
        if not self.chat_id:
            raise BotError("Thiếu TELEGRAM_CHAT_ID.")
        result = self._call(
            "sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": text,
                "link_preview_options": {"is_disabled": True},
            },
        )
        if not isinstance(result, dict) or not isinstance(result.get("message_id"), int):
            raise BotError("Telegram: phản hồi gửi tin không hợp lệ; không gửi lại tức thì.")

    def private_chat_ids(self) -> list[int]:
        updates = self._call("getUpdates", json={"timeout": 0, "limit": 100})
        if not isinstance(updates, list):
            raise BotError("Telegram: danh sách cập nhật không hợp lệ.")
        chat_ids = set()
        for update in updates:
            chat = update.get("message", {}).get("chat", {})
            if chat.get("type") == "private" and isinstance(chat.get("id"), int):
                chat_ids.add(chat["id"])
        return sorted(chat_ids)
