from datetime import datetime
from zoneinfo import ZoneInfo

from mu_bot.models import TEAM_ID, Match

TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def kickoff_text(match: Match) -> str:
    if match.kickoff is None or not match.time_valid:
        return "Giờ bóng lăn chưa xác nhận"
    return match.kickoff.astimezone(TIMEZONE).strftime("%H:%M ngày %d/%m/%Y") + " (giờ Việt Nam)"


def remaining_text(match: Match, now: datetime) -> str:
    minutes = max(1, int((match.kickoff - now).total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    parts = [f"{hours} giờ"] if hours else []
    if minutes:
        parts.append(f"{minutes} phút")
    return " ".join(parts)


def reminder(match: Match, now: datetime) -> str:
    lines = [
        "🔔 Manchester United sắp thi đấu!",
        f"{match.home} vs {match.away}",
        f"🏆 {match.league_name}",
        f"🕒 {kickoff_text(match)}",
        f"⏳ Còn khoảng {remaining_text(match, now)}",
    ]
    if match.venue:
        lines.append(f"🏟 {match.venue}")
    if match.url:
        lines.append(match.url)
    return "\n".join(lines)


def schedule_change(match: Match) -> str:
    return "\n".join(
        [
            "📅 Cập nhật giờ bóng lăn",
            f"{match.home} vs {match.away}",
            f"🏆 {match.league_name}",
            f"🕒 {kickoff_text(match)}",
        ]
    )


def result_message(match: Match) -> str:
    penalties = match.home_penalties is not None and match.away_penalties is not None
    mu_won = match.home_winner if match.home_id == TEAM_ID else match.away_winner
    opponent_won = match.away_winner if match.home_id == TEAM_ID else match.home_winner
    if mu_won or opponent_won:
        outcome = "Manchester United thắng!" if mu_won else "Manchester United thua."
    elif penalties:
        mu_penalties = match.home_penalties if match.home_id == TEAM_ID else match.away_penalties
        other_penalties = match.away_penalties if match.home_id == TEAM_ID else match.home_penalties
        outcome = (
            "Manchester United thắng!"
            if mu_penalties > other_penalties
            else "Manchester United thua."
        )
    elif match.status == "STATUS_FINAL_PEN":
        outcome = "Manchester United kết thúc trận sau luân lưu."
    elif match.home_score == match.away_score:
        outcome = "Manchester United hòa."
    else:
        mu_score = match.home_score if match.home_id == TEAM_ID else match.away_score
        other_score = match.away_score if match.home_id == TEAM_ID else match.home_score
        outcome = (
            "Manchester United thắng!" if mu_score > other_score else "Manchester United thua."
        )
    if match.status == "STATUS_FINAL_PEN":
        phase = "Sau luân lưu"
    elif match.status == "STATUS_FINAL_AET":
        phase = "Sau hiệp phụ"
    else:
        phase = "Đã kết thúc"
    lines = [
        f"⚽ {outcome}",
        f"{match.home} {match.home_score}–{match.away_score} {match.away}",
        f"🏆 {match.league_name}",
        f"🏁 {phase}",
    ]
    if penalties:
        lines.append(f"Luân lưu: {match.home_penalties}–{match.away_penalties}")
    elif match.status == "STATUS_FINAL_PEN":
        lines.append("Nguồn chưa cung cấp tỷ số luân lưu.")
    if match.url:
        lines.append(match.url)
    return "\n".join(lines)
