# Butler Bot — shared utilities
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""Timezone, date math, formatting, work schedule logic."""
from datetime import datetime, date, timedelta, time
import json
import zoneinfo

from config import TIMEZONE

TZ = zoneinfo.ZoneInfo(TIMEZONE)


# ── Time ──

def now() -> datetime:
    return datetime.now(TZ)


def today() -> date:
    return now().date()


def days_until(target: date) -> int:
    return (target - today()).days


# ── Friendly Formatting ──

def friendly_date(d: date) -> str:
    delta = days_until(d)
    if delta == 0:
        return "TODAY"
    if delta == 1:
        return "tomorrow"
    if delta < 0:
        return f"{abs(delta)}d — needs attention"
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


# ── Work Schedule ──

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


def _get_payday_type(chat_id: int = None) -> str:
    """Read payday_type from settings. Returns 'weekly_friday' if not set."""
    if chat_id is None:
        return "weekly_friday"
    from database import db
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE chat_id = ? AND key = 'payday_type'",
            (chat_id,)
        ).fetchone()
    return row["value"] if row else "weekly_friday"


def is_payday(d: date | None = None, chat_id: int = None) -> bool:
    d = d or today()
    ptype = _get_payday_type(chat_id)
    if ptype == "weekly_friday":
        return d.weekday() == 4
    if ptype == "biweekly_friday":
        # Biweekly from a fixed epoch (Jan 2, 2026 was a Friday)
        epoch = date(2026, 1, 2)
        return d.weekday() == 4 and ((d - epoch).days // 7) % 2 == 0
    if ptype == "first_fifteenth":
        return d.day in (1, 15)
    # Default fallback
    return d.weekday() == 4


def next_payday(chat_id: int = None, from_date: date | None = None) -> date:
    d = (from_date or today()) + timedelta(days=1)
    # Search up to 35 days ahead
    for _ in range(35):
        if is_payday(d, chat_id):
            return d
        d += timedelta(days=1)
    # Fallback: next Friday
    return next_weekday(4, from_date)


def check_override(d: date, chat_id: int) -> int | None:
    """Returns 1 (working), 0 (off), or None (no override)."""
    from database import db
    with db() as conn:
        row = conn.execute(
            "SELECT is_working FROM shift_overrides WHERE chat_id = ? AND override_date = ?",
            (chat_id, d.isoformat())
        ).fetchone()
    return row["is_working"] if row else None


def get_user_shift(chat_id: int) -> dict | None:
    """Load a user's shift config. Returns dict with keys:
    w1, w2, anchor, shift_type — or None if no shift set."""
    from database import db
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM shifts WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
            (chat_id,)
        ).fetchone()
    if not row or not row["week1_days"]:
        return None
    return {
        "w1": json.loads(row["week1_days"]),
        "w2": json.loads(row["week2_days"] or "[]") or json.loads(row["week1_days"]),
        "anchor": row["anchor_date"] or "2026-03-30",
        "shift_type": row["shift_type"] or "7p-7a",
    }


def is_working(chat_id: int, d: date = None) -> bool:
    """Full check: override first, then schedule rotation."""
    d = d or today()
    override = check_override(d, chat_id)
    if override is not None:
        return bool(override)
    shift = get_user_shift(chat_id)
    if not shift:
        return False
    return is_work_day(d, shift["anchor"], shift["w1"], shift["w2"])


# ── Shared Date Resolution ──

def resolve_date(date_value, reference_date):
    """Resolve a partner/recurring date (MM-DD or ISO) to a date object.
    Returns None on bad data."""
    try:
        if len(date_value) == 5:  # MM-DD recurring
            for year in [reference_date.year, reference_date.year + 1]:
                target = date(year, int(date_value[:2]), int(date_value[3:]))
                if target >= reference_date:
                    return target
        else:
            return date.fromisoformat(date_value)
    except (ValueError, TypeError):
        return None


def partner_emoji(pd_row):
    """Get display emoji for a partner date row (or partner dict)."""
    from keyboards import RELATIONSHIP_TYPES
    rel = pd_row.get("relationship_type")
    if rel and rel in RELATIONSHIP_TYPES:
        return RELATIONSHIP_TYPES[rel][0]
    return pd_row.get("emoji") or "💜"


# ── ASCII Calendar ──

def ascii_week_calendar(
    start: date,
    work_days: list[date],
    events: dict[date, list[str]],  # date -> list of emoji+label
) -> str:
    """Build a text-based week view. Sunday–Saturday layout."""
    lines = []
    header = "┌" + "─" * 50 + "┐"
    footer = "└" + "─" * 50 + "┘"
    lines.append(header)

    # Sunday-first: iterate in Sun-Sat order
    # start is already the Sunday of the week (set by caller)
    for i in range(7):
        d = start + timedelta(days=i)
        day_label = d.strftime("%a %m/%d")
        is_today_flag = d == today()
        marker = " ◀ TODAY" if is_today_flag else ""

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
