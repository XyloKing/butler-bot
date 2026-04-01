# Butler Bot — Quality-of-Life Suggestions Engine
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""Behavioral nudges for daily check-ins. Draws from the behavioral-intelligence-spec
research: wellness checks, partner nudges, sleep conflict warnings, med encouragement."""

import random
from datetime import date, timedelta
from database import db
from helpers import today, days_until, is_payday, friendly_date, is_working


def get_toggle(chat_id: int, key: str, default: bool = True) -> bool:
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE chat_id = ? AND key = ?",
            (chat_id, f"toggle_{key}"),
        ).fetchone()
    return row["value"] == "1" if row else default


def get_suggestions(chat_id: int, time_of_day: str = "afternoon") -> list[str]:
    """Returns 1-3 contextual suggestions for a check-in message."""
    suggestions = []
    d = today()

    if get_toggle(chat_id, "wellness_checks"):
        suggestions += _wellness(chat_id, d, time_of_day)

    if get_toggle(chat_id, "partner_nudges"):
        nudge = _partner_nudge(chat_id, d)
        if nudge:
            suggestions.append(nudge)

    if get_toggle(chat_id, "med_reminders"):
        nudge = _med_nudge(chat_id)
        if nudge:
            suggestions.append(nudge)

    deadline = _deadline_nudge(chat_id, d)
    if deadline:
        suggestions.append(deadline)

    conflict = _sleep_conflict(chat_id, d)
    if conflict:
        suggestions.append(conflict)

    # Recovery day social guard warning
    recovery_warn = _recovery_social_warning(chat_id, d, time_of_day)
    if recovery_warn:
        suggestions.insert(0, recovery_warn)  # Put it at the top

    # Cap at 3 to avoid overwhelm
    return random.sample(suggestions, min(3, len(suggestions))) if len(suggestions) > 3 else suggestions


def _wellness(chat_id, d, time_of_day):
    tips = []
    working_now = is_working(chat_id, d)
    worked_yesterday = is_working(chat_id, d - timedelta(days=1))
    off_today = not working_now

    if working_now and time_of_day == "evening":
        tips.append(random.choice([
            "💧 Hydration check — have you had water recently?",
            "🍎 Fuel check — when did you last eat something?",
            "🧘 Quick stretch — even 30 seconds helps.",
            "😤 Take 3 deep breaths. Your body's running a marathon tonight.",
        ]))

    if worked_yesterday and off_today and time_of_day == "afternoon":
        tips.append(random.choice([
            "😴 Recovery day — protect your sleep window today.",
            "☀️ Try to get 15 min of sunlight before your sleep window.",
            "🫧 Self-care day — you earned it after last night's shift.",
        ]))

    return tips


def _partner_nudge(chat_id, d):
    with db() as conn:
        partners = conn.execute("SELECT * FROM partners WHERE chat_id = ?", (chat_id,)).fetchall()

    for p in partners:
        freq = p.get("interaction_freq") or "flexible"
        if freq == "flexible":
            continue

        with db() as conn:
            last = conn.execute(
                "SELECT date_value FROM partner_dates WHERE partner_id = ? AND chat_id = ? "
                "AND recurring = 0 ORDER BY date_value DESC LIMIT 1",
                (p["id"], chat_id),
            ).fetchone()

        if not last:
            created = p["created_at"][:10] if p.get("created_at") else None
            if created and (d - date.fromisoformat(created)).days > 7:
                return f"💜 You haven't logged time with {p['name']} yet. Maybe reach out?"
            continue

        try:
            last_date = date.fromisoformat(last["date_value"])
        except (ValueError, TypeError):
            continue

        days_since = (d - last_date).days
        threshold = {"daily": 2, "weekly": 10, "biweekly": 18, "monthly": 35}.get(freq, 999)

        if days_since >= threshold:
            rel = p.get("relationship_type")
            name = p["name"]
            if rel == "partner":
                return f"💜 It's been {days_since} days since your last date with {name}. Time to plan one?"
            elif rel == "family":
                return f"🧡 Haven't connected with {name} in {days_since} days. A quick call?"
            return f"💚 It's been a while since you've seen {name}. Worth reaching out?"

    return None


def _med_nudge(chat_id):
    with db() as conn:
        meds = conn.execute("SELECT * FROM medications WHERE chat_id = ?", (chat_id,)).fetchall()
    if not meds:
        return None
    if all(m["taken_today"] for m in meds):
        return random.choice([
            "💊 All meds taken today — great job keeping up.",
            "💊 Meds handled. Consistency is a superpower.",
            "💊 Look at you, staying on top of your meds. 🫡",
        ])
    return None


def _deadline_nudge(chat_id, d):
    with db() as conn:
        creds = conn.execute(
            "SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0", (chat_id,)
        ).fetchall()
    for c in creds:
        delta = days_until(date.fromisoformat(c["expiry_date"]))
        if 7 < delta <= 30:
            return f"🎓 Heads up — {c['name']} expires in {delta} days. Got a renewal plan?"

    with db() as conn:
        bills = conn.execute(
            "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0", (chat_id,)
        ).fetchall()
    for b in bills:
        if b["due_day"]:
            due = d.replace(day=min(b["due_day"], 28))
            if due < d:
                due = due.replace(month=due.month + 1) if due.month < 12 else due.replace(year=due.year + 1, month=1)
            delta = (due - d).days
            if 2 <= delta <= 5 and not is_payday(d):
                return f"💸 {b['name']} is due in {delta} days. Plan ahead."
    return None


def _sleep_conflict(chat_id, d):
    if not is_working(chat_id, d):
        return None
    tomorrow = d + timedelta(days=1)
    with db() as conn:
        appts = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND event_date = ? AND done = 0",
            (chat_id, tomorrow.isoformat()),
        ).fetchall()
    for a in appts:
        if a["event_time"]:
            try:
                hour = int(a["event_time"].split(":")[0])
                if hour < 14:
                    return (f"⚠️ You're working tonight but have \"{a['title']}\" "
                            f"at {a['event_time']} tomorrow. That's during your sleep window.")
            except (ValueError, TypeError):
                pass
    return None


def _recovery_social_warning(chat_id, d, time_of_day):
    """Warn if today is a recovery day and there are social appointments before 5pm."""
    worked_yesterday = is_working(chat_id, d - timedelta(days=1))
    working_today = is_working(chat_id, d)
    if not (worked_yesterday and not working_today):
        return None  # Not a recovery day
    # Check for social appointments today before 5pm
    with db() as conn:
        appts = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND event_date = ? "
            "AND done = 0 AND category = 'social'",
            (chat_id, d.isoformat()),
        ).fetchall()
    for a in appts:
        if a["event_time"]:
            try:
                hour = int(a["event_time"].split(":")[0])
                if hour < 17:
                    return (f"🚫 Recovery day — \"{a['title']}\" is at {a['event_time']}. "
                            "Social plans before 5pm on recovery days hit hard.")
            except (ValueError, TypeError):
                pass
    return None
