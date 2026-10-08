import time
from collections.abc import Callable
from typing import Any

import httpx

from mu_bot.errors import BotError


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    service: str,
    retry_safe: bool = True,
    allow_missing: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Retry reads and explicit throttling; never expose URLs, bodies or raw exceptions."""
    for attempt in range(3):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.RequestError:
            if retry_safe and attempt < 2:
                sleep(2**attempt)
                continue
            raise BotError(
                f"{service}: lỗi mạng hoặc timeout; không xác định được kết quả yêu cầu."
            ) from None
        if response.status_code == 404 and allow_missing:
            return None
        if response.status_code == 429:
            delay: Any = response.headers.get("Retry-After", "1")
            try:
                delay = response.json().get("parameters", {}).get("retry_after", delay)
                delay = float(delay)
            except (ValueError, TypeError, AttributeError):
                delay = 1
            if 0 <= delay <= 30 and attempt < 2:
                sleep(delay)
                continue
        if retry_safe and response.status_code >= 500 and attempt < 2:
            sleep(2**attempt)
            continue
        if not response.is_success:
            raise BotError(f"{service}: HTTP {response.status_code}.")
        try:
            body = response.json()
        except ValueError:
            raise BotError(f"{service}: phản hồi không phải JSON hợp lệ.") from None
        if not isinstance(body, dict):
            raise BotError(f"{service}: cấu trúc phản hồi không hợp lệ.")
        return body
    raise BotError(f"{service}: quá số lần thử lại.")
