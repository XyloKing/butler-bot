"""
Shared utilities: timezone, date math, formatting, work schedule logic.
"""
from datetime import datetime, date, timedelta, time
import json
import zoneinfo

from config import TIMEZONE

TZ = zoneinfo.ZoneInfo(TIMEZONE)


# ─── Time ────────────────────────────────────────────────────

def now() -> datetime:
    return datetime.now(TZ)


def today() -> date:
    return now().date()


def days_until(target: date) -> int:
    return (target - today()).days


# ─── Friendly Formatting ────────────────────────────────────

def friendly_date(d: date) -> str:
    delta = days_until(d)
    if delta == 0:
        return "TODAY"
    if delta == 1:
        return "tomorrow"
    if delta < 0:
        return f"{abs(delta)}d OVERDUE"
    if delta <= 7:
        return f"in {delta}d ({d.strftime('%A')})"
    return f"{d.strftime('%b %d, %Y')} ({delta}d)"


def urgency_emoji(days: int) -> str:
    if days < 0:  return "🔴"
    if days == 0: return "🚨"
    if days <= 3:  return "🟠"
    if days <= 7:  return "🟡"
    if days <= 14: return "🔵"
    if days <= 30: return "⚪"
    return "✅"


def format_money(amount: float | None) -> str:
    if amount is None:
        return "TBD"
    return f"${amount:,.2f}"


# ─── Work Schedule ───────────────────────────────────────────

def is_work_day(d: date, anchor: str, week1: list[int], week2: list[int]) -> bool:
    """Check if date is a scheduled work day given user's rotation."""
    anchor_date = date.fromisoformat(anchor)
    delta_days = (d - anchor_date).days
    if delta_days < 0:
        return False
    week_num = (delta_days // 7) % 2
    weekday = d.weekday()
    return weekday in (week1 if week_num == 0 else week2)


def get_shift_info(d: date, anchor: str, week1: list[int], week2: list[int], shift_type: str = "7p-7a") -> str:
    """Return a human-readable shift status for a date."""
    if is_work_day(d, anchor, week1, week2):
        return f"🏥 Work {shift_type}"
    # Check if yesterday was a work day (post-run day)
    yesterday = d - timedelta(days=1)
    if is_work_day(yesterday, anchor, week1, week2):
        return "😴 Post-shift recovery"
    return "🏠 Off"


def next_weekday(weekday: int, from_date: date | None = None) -> date:
    """Next occurrence of a weekday (0=Mon, 4=Fri, etc.)."""
    d = from_date or today()
    days_ahead = weekday - d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def is_payday(d: date | None = None, payday_weekday: int = 4) -> bool:
    return (d or today()).weekday() == payday_weekday


def next_payday(payday_weekday: int = 4, from_date: date | None = None) -> date:
    return next_weekday(payday_weekday, from_date)


def check_override(d: date, chat_id: int) -> int | None:
    """
    Check if there's a shift override for this date.
    Returns 1 (working), 0 (off), or None (no override).
    """
    from database import db
    with db() as conn:
        row = conn.execute(
            "SELECT is_working FROM shift_overrides WHERE chat_id = ? AND override_date = ?",
            (chat_id, d.isoformat())
        ).fetchone()
    if row:
        return row["is_working"]
    return None


# ─── ASCII Calendar ──────────────────────────────────────────

def ascii_week_calendar(
    start: date,
    work_days: list[date],
    events: dict[date, list[str]],  # date -> list of emoji+label
) -> str:
    """Build a text-based week view."""
    lines = []
    header = "┌" + "─" * 50 + "┐"
    footer = "└" + "─" * 50 + "┘"
    lines.append(header)

    for i in range(7):
        d = start + timedelta(days=i)
        day_label = d.strftime("%a %m/%d")
        is_today = d == today()
        marker = " ◀ TODAY" if is_today else ""

        if d in work_days:
            shift = "🏥 Work"
        else:
            shift = "🏠 Off"

        line = f"│ {day_label}  {shift}{marker}"
        line = line.ljust(51) + "│"
        lines.append(line)

        # Events for this day
        day_events = events.get(d, [])
        for ev in day_events:
            ev_line = f"│   ↳ {ev}"
            ev_line = ev_line.ljust(51) + "│"
            lines.append(ev_line)

    lines.append(footer)
    return "\n".join(lines)
