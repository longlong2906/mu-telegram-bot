import argparse
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from mu_bot.errors import BotError
from mu_bot.espn import ESPN
from mu_bot.messages import kickoff_text
from mu_bot.service import check
from mu_bot.state import GitHubStore, LocalStore, StateStore
from mu_bot.telegram import Telegram


def make_store(client: httpx.Client) -> StateStore:
    default = "github" if os.getenv("GITHUB_ACTIONS") == "true" else "local"
    backend = os.getenv("STATE_BACKEND", default)
    if backend == "github":
        return GitHubStore(
            client, os.getenv("GITHUB_REPOSITORY", ""), os.getenv("GITHUB_TOKEN", "")
        )
    if backend == "local":
        return LocalStore(Path(os.getenv("STATE_FILE", ".state/state.json")))
    raise BotError("STATE_BACKEND phải là local hoặc github.")


def main(argv: list[str] | None = None) -> int:
    # Windows pipes may default to cp1252; Vietnamese and emoji require UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Thông báo trận Manchester United trên Telegram")
    commands = parser.add_subparsers(dest="command", required=True)
    checker = commands.add_parser("check", help="Kiểm tra lịch và kết quả một lần")
    checker.add_argument(
        "--dry-run", action="store_true", help="Chỉ xem, không gửi hoặc ghi trạng thái"
    )
    commands.add_parser("chat-id", help="Lấy ID các chat cá nhân đã nhắn cho bot")
    args = parser.parse_args(argv)
    # httpx logs full URLs at INFO; a Telegram token is embedded in that URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        with httpx.Client(timeout=20) as client:
            if args.command == "chat-id":
                ids = Telegram(client, os.getenv("TELEGRAM_BOT_TOKEN", "")).private_chat_ids()
                if not ids:
                    print("Chưa thấy chat cá nhân. Nhấn Start hoặc gửi /start cho bot rồi thử lại.")
                for chat_id in ids:
                    print(f"TELEGRAM_CHAT_ID={chat_id}")
                return 0
            sender = None
            if not args.dry_run:
                chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
                if not chat_id or not chat_id.isdecimal():
                    raise BotError("TELEGRAM_CHAT_ID phải là ID số dương của chat cá nhân.")
                sender = Telegram(client, os.getenv("TELEGRAM_BOT_TOKEN", ""), chat_id)
            now = datetime.now(UTC)
            report = check(ESPN(client), make_store(client), sender, now, dry_run=args.dry_run)
            mode = "DRY-RUN, không gửi hoặc ghi trạng thái" if args.dry_run else "Đã kiểm tra"
            print(
                f"{mode}: {len(report.matches)} trận chính thức, {len(report.messages)} thông báo."
            )
            if report.initialized:
                print("Khởi tạo: bỏ qua các kết quả đã kết thúc trước lần kiểm tra đầu.")
            if args.dry_run:
                for message in report.messages:
                    print(f"\n{message}\n")
                upcoming = sorted(
                    (match for match in report.matches if match.kickoff and match.kickoff > now),
                    key=lambda match: match.kickoff,
                )
                for match in upcoming[:3]:
                    print(f"Sắp tới: {match.home} vs {match.away} — {kickoff_text(match)}")
        return 0
    except BotError as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
