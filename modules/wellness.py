# Butler Bot — Wellness state engine
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
Silent behavior tracking + curiosity-framed insights.

Two layers, kept apart on purpose:

  1. Internal log — every action logged to `wellness_events` as neutral data
     (taken / skipped / paid / logged). Other modules call `log_event()` on
     every relevant action and don't think about it again.
  2. User-facing surface — `get_insight()` runs over rolling windows and
     returns at most one curious sentence. Never says "missed", "failed",
     "broke", or "overdue". The shame language is what the research
     specifically warns against (see research-behavior-tracking.md §6).

Recovery mode is a per-user toggle stored in the existing `settings` table
(no new column). When on, the suggestions engine drops to a bare-bones
"meds, water, one nice thing" set.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import date, datetime, timedelta

from database import db
from helpers import is_working, today

logger = logging.getLogger(__name__)


VALID_CATEGORIES = {"meds", "bills", "me_time", "dates", "credentials", "car", "notes"}
POSITIVE_TYPES = {"taken", "paid", "logged"}
NEGATIVE_TYPES = {"skipped", "missed", "unpaid"}


# ── Logging ──────────────────────────────────────────────────────────────

def log_event(chat_id: int, category: str, event_type: str, ref_id: int | None = None) -> None:
    """Silently record a wellness event. Never raises — logging must not
    disrupt the user-facing flow that triggered it."""
    if category not in VALID_CATEGORIES:
        # Don't crash on a typo — just drop it. The bot stays alive.
        logger.debug("wellness.log_event: unknown category %r", category)
        return

    try:
        n = datetime.now()
        ctx = {
            "day_of_week": n.weekday(),  # 0 = Monday
            "hour": n.hour,
            "shift_day": is_working(chat_id, n.date()),
        }
        with db() as conn:
            conn.execute(
                "INSERT INTO wellness_events (chat_id, category, event_type, ref_id, context) "
                "VALUES (?, ?, ?, ?, ?)",
                (chat_id, category, event_type, ref_id, json.dumps(ctx)),
            )
    except Exception as e:
        # Belt-and-suspenders: swallow anything DB-related so the user-facing
        # action that triggered this log still completes cleanly.
        logger.warning("wellness.log_event failed: %s", e)


# ── Pattern detection ────────────────────────────────────────────────────

def get_pattern(chat_id: int, category: str, days: int = 7) -> dict:
    """Neutral summary over the last `days` days for one category."""
    cutoff = (today() - timedelta(days=days)).isoformat()
    with db() as conn:
        rows = conn.execute(
            "SELECT event_type, ref_id, context, logged_at FROM wellness_events "
            "WHERE chat_id = ? AND category = ? AND date(logged_at) >= ? "
            "ORDER BY logged_at",
            (chat_id, category, cutoff),
        ).fetchall()

    positive_dates: set[date] = set()
    dow_counts: dict[int, int] = {i: 0 for i in range(7)}
    last_positive: date | None = None
    shift_positive = 0
    total_positive = 0

    for r in rows:
        event_type = r["event_type"]
        if event_type not in POSITIVE_TYPES:
            continue
        try:
            ev_date = date.fromisoformat(r["logged_at"][:10])
        except (ValueError, TypeError):
            continue
        positive_dates.add(ev_date)
        dow_counts[ev_date.weekday()] = dow_counts.get(ev_date.weekday(), 0) + 1
        total_positive += 1
        if last_positive is None or ev_date > last_positive:
            last_positive = ev_date
        try:
            ctx = json.loads(r["context"]) if r["context"] else {}
            if ctx.get("shift_day"):
                shift_positive += 1
        except (ValueError, TypeError):
            pass

    # Gap = how many of the last `days` days had no positive event
    gaps = 0
    d = today()
    for i in range(days):
        if (d - timedelta(days=i)) not in positive_dates:
            gaps += 1

    shift_correlation = (shift_positive / total_positive) if total_positive else 0.0

    return {
        "total_events": len(rows),
        "positive": total_positive,
        "gaps": gaps,
        "last_positive": last_positive,
        "day_of_week_pattern": dow_counts,
        "shift_correlation": round(shift_correlation, 2),
    }


# ── Insight generation ───────────────────────────────────────────────────

# Curiosity-framed phrases. Sourced from research §5 + §10.
# Never "missed", "failed", "broke", "overdue", "haven't done".

_MEDS_PHRASES = [
    "Hey — looks like the evening dose has been tricky lately. Anything different going on? No pressure.",
    "I noticed meds have been harder to keep up with this week. Shifts been rough?",
    "Just checking in — meds have been a stretch the last few days. Want to talk about timing?",
]

_BILLS_PHRASES = [
    "Heads up — a bill is coming up. Want to knock it out in 90 seconds, or save it for later?",
    "One of your bills is sitting open and getting close. Want to handle it now or set a reminder?",
]

_ME_TIME_PHRASES = [
    "It's been a stretch since you logged anything just for you. Want to schedule something small — 20 minutes, low spice?",
    "I noticed you haven't had much you-time lately. Even 30 minutes counts.",
    "Personal time slot's been quiet. Want to plan something tiny, or pass for now?",
]

_DATES_PHRASES = [
    "Feels like a good week to make some plans. Anyone you've been meaning to see?",
    "Quiet week on the social front. Want to reach out to someone, or let it ride?",
]


def get_insight(chat_id: int, d: date | None = None) -> str | None:
    """Return at most one curiosity-framed insight, or None.

    Threshold rule (research §6):
      1 gap = silent
      2 gaps = soft (still suppressed for now — daily nudge would feel like a nag)
      3+ gaps = curious offer

    We pick the first category that crosses threshold, in priority order:
    meds → bills → me_time → dates. Avoids stacking three curious questions
    in one digest.
    """
    if d is None:
        d = today()

    # Recovery mode users get nothing here — the suggestions engine handles
    # them with a smaller, gentler set.
    if is_recovery_mode(chat_id):
        return None

    rng = random.Random()  # local instance so tests can be deterministic if needed

    # Meds — only if the user actually has meds tracked.
    if _has_records(chat_id, "medications"):
        meds = get_pattern(chat_id, "meds", days=7)
        if meds["gaps"] >= 3 and meds["positive"] >= 1:
            return rng.choice(_MEDS_PHRASES)

    # Bills — surface if there's an unpaid bill within 5 days AND the user
    # hasn't logged a `paid` event in 14 days. Matches research §10.
    bill_phrase = _bill_insight(chat_id, d)
    if bill_phrase:
        return bill_phrase

    # Me-time — 5+ days without a `logged` event.
    me_pattern = get_pattern(chat_id, "me_time", days=7)
    if me_pattern["gaps"] >= 5:
        return rng.choice(_ME_TIME_PHRASES)

    # Dates — if user has partners with daily/weekly/biweekly cadence and
    # nothing logged in the last 7 days.
    if _expects_dates(chat_id):
        date_pattern = get_pattern(chat_id, "dates", days=7)
        if date_pattern["positive"] == 0:
            return rng.choice(_DATES_PHRASES)

    return None


def _has_records(chat_id: int, table: str) -> bool:
    with db() as conn:
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE chat_id = ? LIMIT 1", (chat_id,)
        ).fetchone()
    return row is not None


def _bill_insight(chat_id: int, d: date) -> str | None:
    bill_pattern = get_pattern(chat_id, "bills", days=14)
    if bill_pattern["positive"] > 0:
        return None  # they paid something recently — leave them alone

    with db() as conn:
        bills = conn.execute(
            "SELECT name, due_day, due_date FROM bills "
            "WHERE chat_id = ? AND paid_this_cycle = 0",
            (chat_id,),
        ).fetchall()
    if not bills:
        return None

    for b in bills:
        delta = _days_until_due(b, d)
        if delta is not None and 0 <= delta <= 5:
            return random.choice(_BILLS_PHRASES)
    return None


def _days_until_due(bill_row, d: date) -> int | None:
    """Days until the next occurrence of this bill's due_day or due_date."""
    try:
        if bill_row["due_day"]:
            due = d.replace(day=min(int(bill_row["due_day"]), 28))
            if due < d:
                due = (due.replace(month=due.month + 1) if due.month < 12
                       else due.replace(year=due.year + 1, month=1))
            return (due - d).days
        if bill_row["due_date"]:
            return (date.fromisoformat(bill_row["due_date"]) - d).days
    except (ValueError, TypeError):
        return None
    return None


def _expects_dates(chat_id: int) -> bool:
    """Does the user have any partner with a non-flexible cadence?"""
    with db() as conn:
        row = conn.execute(
            "SELECT 1 FROM partners WHERE chat_id = ? "
            "AND interaction_freq IN ('daily', 'weekly', 'biweekly') LIMIT 1",
            (chat_id,),
        ).fetchone()
    return row is not None


# ── Recovery mode ────────────────────────────────────────────────────────

_RECOVERY_KEY = "recovery_mode"


def is_recovery_mode(chat_id: int) -> bool:
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE chat_id = ? AND key = ?",
            (chat_id, _RECOVERY_KEY),
        ).fetchone()
    return bool(row and row["value"] == "1")


def set_recovery_mode(chat_id: int, active: bool) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (chat_id, key, value) VALUES (?, ?, ?)",
            (chat_id, _RECOVERY_KEY, "1" if active else "0"),
        )
