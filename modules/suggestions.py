"""
💡 Quality-of-Life Suggestions Engine.
Generates behavioral nudges and wellness tips for daily check-ins,
based on the behavioral-intelligence-spec.md research.

Categories:
- Hydration / nutrition (mid-shift wellness)
- Sleep hygiene reminders (for night shift workers)
- Partner check-in nudges (based on interaction frequency)
- Credential/bill awareness
- Medication adherence encouragement
- Schedule-aware activity suggestions
"""
import json
import random
from datetime import date, timedelta
from database import db
from helpers import today, days_until, is_work_day, is_payday, friendly_date


def get_toggle(chat_id: int, key: str, default: bool = True) -> bool:
    """Check if a feature toggle is enabled for this user."""
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE chat_id = ? AND key = ?",
            (chat_id, f"toggle_{key}"),
        ).fetchone()
    if row:
        return row["value"] == "1"
    return default


def get_suggestions(chat_id: int, time_of_day: str = "afternoon") -> list[str]:
    """Generate contextual quality-of-life suggestions for a check-in.

    Returns a list of 1-3 short suggestion strings.
    """
    suggestions = []
    d = today()

    # ── Wellness checks (Feature 57: Mid-Shift Wellness) ──────────
    if get_toggle(chat_id, "wellness_checks"):
        working_tonight = _is_working(chat_id, d)
        if working_tonight and time_of_day == "evening":
            wellness_tips = [
                "💧 Hydration check — have you had water recently?",
                "🍎 Fuel check — when did you last eat something?",
                "🧘 Quick stretch — even 30 seconds helps.",
                "😤 Take 3 deep breaths. Your body's running a marathon tonight.",
            ]
            suggestions.append(random.choice(wellness_tips))

        # Post-shift recovery suggestions (Feature 58)
        yesterday = d - timedelta(days=1)
        worked_yesterday = _is_working(chat_id, yesterday)
        not_working_today = not _is_working(chat_id, d)
        if worked_yesterday and not_working_today and time_of_day == "afternoon":
            recovery_tips = [
                "😴 Recovery day — protect your sleep window today.",
                "☀️ Try to get 15 min of sunlight before your sleep window.",
                "🫧 Self-care day — you earned it after last night's shift.",
            ]
            suggestions.append(random.choice(recovery_tips))

    # ── Partner check-in nudges (Feature 18 + interaction freq) ─────
    if get_toggle(chat_id, "partner_nudges"):
        partner_nudge = _get_partner_nudge(chat_id, d)
        if partner_nudge:
            suggestions.append(partner_nudge)

    # ── Medication encouragement (Feature 82: Micro-Celebrations) ────
    if get_toggle(chat_id, "med_reminders"):
        med_nudge = _get_med_nudge(chat_id)
        if med_nudge:
            suggestions.append(med_nudge)

    # ── Upcoming deadline awareness ─────────────────────────────────
    deadline_nudge = _get_deadline_nudge(chat_id, d)
    if deadline_nudge:
        suggestions.append(deadline_nudge)

    # ── Schedule conflict warning (Feature 59) ──────────────────────
    conflict = _check_sleep_conflicts(chat_id, d)
    if conflict:
        suggestions.append(conflict)

    # Limit to 3 max to avoid overwhelm (ADHD-friendly)
    if len(suggestions) > 3:
        suggestions = random.sample(suggestions, 3)

    return suggestions


def _is_working(chat_id: int, d: date) -> bool:
    """Check if user is working on a given date."""
    # Check overrides first
    with db() as conn:
        override = conn.execute(
            "SELECT is_working FROM shift_overrides WHERE chat_id = ? AND override_date = ?",
            (chat_id, d.isoformat()),
        ).fetchone()
    if override:
        return bool(override["is_working"])

    with db() as conn:
        shift = conn.execute(
            "SELECT * FROM shifts WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
    if not shift or not shift["week1_days"]:
        return False
    w1 = json.loads(shift["week1_days"])
    w2 = json.loads(shift["week2_days"] or "[]") or w1
    try:
        anchor = shift["anchor_date"] or "2026-03-30"
    except (IndexError, KeyError):
        anchor = "2026-03-30"
    return is_work_day(d, anchor, w1, w2)


def _get_partner_nudge(chat_id: int, d: date) -> str | None:
    """Check if any partner is overdue for interaction based on their frequency."""
    with db() as conn:
        partners = conn.execute(
            "SELECT * FROM partners WHERE chat_id = ?", (chat_id,)
        ).fetchall()

    for p in partners:
        try:
            freq = p["interaction_freq"] or "flexible"
        except (IndexError, KeyError):
            freq = "flexible"

        if freq == "flexible":
            continue

        # Check last interaction (most recent partner_date)
        with db() as conn:
            last_date = conn.execute(
                "SELECT date_value FROM partner_dates WHERE partner_id = ? AND chat_id = ? "
                "AND recurring = 0 ORDER BY date_value DESC LIMIT 1",
                (p["id"], chat_id),
            ).fetchone()

        if not last_date:
            # No dates logged — nudge after a few days
            try:
                created = date.fromisoformat(p["created_at"][:10])
                if (d - created).days > 7:
                    name = p["name"]
                    return f"💜 You haven't logged time with {name} yet. Maybe reach out?"
            except (ValueError, TypeError):
                pass
            continue

        try:
            last = date.fromisoformat(last_date["date_value"])
        except (ValueError, TypeError):
            continue

        days_since = (d - last).days
        threshold = {"daily": 2, "weekly": 10, "biweekly": 18, "monthly": 35}.get(freq, 999)

        if days_since >= threshold:
            name = p["name"]
            try:
                rel = p["relationship_type"]
            except (IndexError, KeyError):
                rel = None
            if rel == "partner":
                return f"💜 It's been {days_since} days since your last date with {name}. Time to plan one?"
            elif rel == "family":
                return f"🧡 Haven't connected with {name} in {days_since} days. A quick call?"
            else:
                return f"💚 It's been a while since you've seen {name}. Worth reaching out?"

    return None


def _get_med_nudge(chat_id: int) -> str | None:
    """Positive reinforcement for medication adherence."""
    with db() as conn:
        meds = conn.execute(
            "SELECT * FROM medications WHERE chat_id = ?", (chat_id,)
        ).fetchall()
    if not meds:
        return None

    all_taken = all(m["taken_today"] for m in meds)
    if all_taken:
        celebrations = [
            "💊 All meds taken today — great job keeping up.",
            "💊 Meds handled. Consistency is a superpower.",
            "💊 Look at you, staying on top of your meds. 🫡",
        ]
        return random.choice(celebrations)
    return None


def _get_deadline_nudge(chat_id: int, d: date) -> str | None:
    """Surface approaching deadlines the user might have forgotten."""
    # Credentials expiring within 30 days
    with db() as conn:
        creds = conn.execute(
            "SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0",
            (chat_id,),
        ).fetchall()
    for c in creds:
        exp = date.fromisoformat(c["expiry_date"])
        delta = days_until(exp)
        if 7 < delta <= 30:
            return f"🎓 Heads up — {c['name']} expires in {delta} days. Got a renewal plan?"

    # Bills due within 5 days that aren't paid
    with db() as conn:
        bills = conn.execute(
            "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0",
            (chat_id,),
        ).fetchall()
    for b in bills:
        if b["due_day"]:
            due = d.replace(day=min(b["due_day"], 28))
            if due < d:
                if due.month < 12:
                    due = due.replace(month=due.month + 1)
                else:
                    due = due.replace(year=due.year + 1, month=1)
            delta = (due - d).days
            if 2 <= delta <= 5 and not is_payday(d):
                return f"💸 {b['name']} is due in {delta} days. Payday is {friendly_date(date.fromisoformat('2026-04-04'))} — plan ahead."

    return None


def _check_sleep_conflicts(chat_id: int, d: date) -> str | None:
    """Feature 59: Heads-up if an appointment conflicts with sleep window."""
    working_tonight = _is_working(chat_id, d)
    if not working_tonight:
        return None

    # Check for early morning appointments tomorrow (during sleep window)
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
                if hour < 14:  # Before 2 PM = during sleep window for night shift
                    return (
                        f"⚠️ You're working tonight but have \"{a['title']}\" "
                        f"at {a['event_time']} tomorrow. That's during your sleep window."
                    )
            except (ValueError, TypeError):
                pass
    return None
