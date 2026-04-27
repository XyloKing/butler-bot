# Butler Bot — Suggestions Engine
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""Context-aware suggestions for daily check-ins and on-demand.

Sources every variable in the bot: partners, dates, me-time, meds,
bills, credentials, car, notes, shift schedule. Falls back to a large
pool of general life/wellness suggestions when nothing specific is pending.
"""

import random
from datetime import date, timedelta
from database import db
from helpers import today, days_until, is_payday, friendly_date, is_working


# ── General life suggestion pool ─────────────────────────────────────────
# These cycle regardless of what data exists. 70+ options across categories.

LIFE_SUGGESTIONS = {
    "wellness": [
        "💧 How's your water intake today?",
        "🧘 Even 5 minutes of stillness resets a lot.",
        "🚶 A short walk outside does more than most people think.",
        "😴 Sleep debt compounds. Every bit of rest counts.",
        "🍎 When's the last time you actually ate a full meal?",
        "🫁 Take 3 slow breaths right now. Seriously.",
        "💊 Med check — anything you're supposed to take today?",
        "🧴 Hydrate, stretch, repeat.",
        "🪥 Basic self-care goes a long way on rough days.",
        "📵 Even 30 mins offline is a reset.",
    ],
    "social": [
        "💬 Is there someone you've been meaning to text back?",
        "📞 When's the last time you called someone who matters to you?",
        "🤝 Relationships need deposits too. A quick check-in counts.",
        "💌 Send someone a random 'thinking of you' today.",
        "🫂 Who haven't you seen in a while that you miss?",
        "🎮 Game night is self-care too.",
        "🎵 Music and a friend is a whole evening.",
    ],
    "admin": [
        "📁 Is there a random document or password you've been meaning to find?",
        "📬 Anything sitting in your actual mailbox you've been ignoring?",
        "🔋 Low on anything you use daily? Time to restock?",
        "🧹 One small cleaning task can take 10 minutes and shift your mood.",
        "🗂 Is there a loose end from last week that's still floating?",
        "📲 Any app subscriptions you pay for but don't use?",
        "🔑 When's the last time you updated any important password?",
    ],
    "growth": [
        "📚 Read anything interesting lately? Worth picking up again.",
        "🎯 What's the one thing you want to do this month that you keep pushing?",
        "✏️ Write one sentence about how things are going right now.",
        "🎓 Is there a skill or cert you've wanted to pursue?",
        "🧠 Something you learned this week worth keeping?",
        "🗺 Where do you want to be in 6 months? Even a rough idea helps.",
    ],
    "night_shift_specific": [
        "🌙 Night shift life is different. Your rhythm is valid.",
        "☀️ If you can get 15 min of sunlight before sleep, do it.",
        "🫡 You're keeping people alive at 3am. That matters.",
        "🧃 Electrolytes before a long shift — underrated.",
        "💤 Post-shift sleep is sacred. Protect it.",
        "🏃 Even a short workout after a shift helps your sleep cycle.",
        "🍜 Meal prep before a run of shifts saves your whole week.",
    ],
    "fun": [
        "🎮 What game have you been meaning to go back to?",
        "🎬 Anything on your watch list you haven't touched?",
        "🎵 What's a song that's been in your head lately?",
        "🎯 Random goal: try one new thing this week. Anything.",
        "🛁 When's the last time you genuinely did nothing and it was fine?",
        "📷 Document something. You'll want that memory.",
    ],
    "reflection": [
        "💭 What's something you did well this week?",
        "🙌 You handled something hard lately. Acknowledge it.",
        "🔁 What's one habit you'd like to build or break?",
        "🧭 Are you moving toward something or just maintaining?",
        "🌱 Growth isn't always visible. Trust the process.",
        "✅ You showed up today. That counts.",
    ],
}

ALL_GENERAL = [s for category in LIFE_SUGGESTIONS.values() for s in category]


def get_toggle(chat_id: int, key: str, default: bool = True) -> bool:
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE chat_id = ? AND key = ?",
            (chat_id, f"toggle_{key}"),
        ).fetchone()
    return row["value"] == "1" if row else default


def get_suggestions(chat_id: int, time_of_day: str = "afternoon") -> list[str]:
    """Returns 3-5 suggestions, mixing context-aware and general pool.
    Always returns something even when no data exists.
    """
    from modules.wellness import is_recovery_mode, get_insight

    d = today()
    specific = []
    general = []

    # ── Context-aware suggestions (sourced from all user data) ───────────

    if get_toggle(chat_id, "wellness_checks"):
        specific += _wellness(chat_id, d, time_of_day)

    # Partner status
    if get_toggle(chat_id, "partner_nudges"):
        nudge = _partner_nudge(chat_id, d)
        if nudge:
            specific.append(nudge)

    # Me-time check
    me_time = _me_time_nudge(chat_id, d)
    if me_time:
        specific.append(me_time)

    # Med status
    if get_toggle(chat_id, "med_reminders"):
        med = _med_nudge(chat_id)
        if med:
            specific.append(med)

    # Deadlines (bills, credentials)
    deadline = _deadline_nudge(chat_id, d)
    if deadline:
        specific.append(deadline)

    # Sleep conflict
    if is_working(chat_id, d):
        conflict = _sleep_conflict(chat_id, d)
        if conflict:
            specific.append(conflict)

    # Recovery day
    if not is_working(chat_id, d) and is_working(chat_id, d - timedelta(days=1)):
        specific.append(random.choice([
            "😴 Recovery day. Sleep first, everything else second.",
            "☀️ Try to get some sunlight before your sleep window.",
            "🫧 You earned today. Take it slow.",
        ]))

    # Car items due
    car = _car_nudge(chat_id, d)
    if car:
        specific.append(car)

    # Notes-based suggestion
    note = _note_nudge(chat_id)
    if note:
        specific.append(note)

    # Dates this week status
    date_cap = _date_cap_nudge(chat_id, d)
    if date_cap:
        specific.append(date_cap)

    # Wellness pattern insight (curious, never shaming — see modules/wellness.py)
    insight = get_insight(chat_id, d)
    if insight:
        specific.append(insight)

    # Recovery mode short-circuits the rest: keep the surface tiny and gentle.
    # Strip anything pushy from `specific`, then return a small mix.
    if is_recovery_mode(chat_id):
        gentle = [
            s for s in specific
            if not any(w in s.lower() for w in ("due", "unpaid", "expires", "overdue"))
        ]
        soft_general = [
            "🌱 Recovery mode is on. Tonight: meds, water, one nice thing.",
            "🌱 You're in recovery mode. The rest can wait.",
            "💧 Hydrate. Breathe. That's enough for now.",
        ]
        out = gentle[:1] + random.sample(soft_general, 1)
        return out[:2]

    # ── Fill remaining slots with general suggestions ────────────────────
    # Always include at least 1 general suggestion for variety
    # Shuffle so it doesn't feel like the same rotation
    shuffled_general = random.sample(ALL_GENERAL, min(5, len(ALL_GENERAL)))
    general = shuffled_general

    # Mix: up to 3 specific, at least 1 general, total 3-4
    if len(specific) > 3:
        specific = random.sample(specific, 3)

    result = specific + general
    # Deduplicate while preserving order
    seen = set()
    final = []
    for s in result:
        if s not in seen:
            seen.add(s)
            final.append(s)

    return final[:4]  # Max 4 to avoid overwhelm


# ── Context sources ───────────────────────────────────────────────────────

def _wellness(chat_id, d, time_of_day):
    tips = []
    working_now = is_working(chat_id, d)

    if working_now and time_of_day == "evening":
        tips.append(random.choice([
            "💧 Hydration check — had water recently?",
            "🍎 Fuel check — last real meal?",
            "🧘 30-second stretch — your back will thank you.",
        ]))

    return tips


def _partner_nudge(chat_id, d):
    with db() as conn:
        partners = conn.execute("SELECT * FROM partners WHERE chat_id = ?", (chat_id,)).fetchall()

    for p in partners:
        freq = dict(p).get("interaction_freq") or "flexible"
        if freq == "flexible":
            continue

        with db() as conn:
            last = conn.execute(
                "SELECT date_value FROM partner_dates WHERE partner_id = ? AND chat_id = ? "
                "AND recurring = 0 ORDER BY date_value DESC LIMIT 1",
                (p["id"], chat_id),
            ).fetchone()

        if not last:
            created = p["created_at"][:10] if dict(p).get("created_at") else None
            if created and (d - date.fromisoformat(created)).days > 7:
                return f"It's been a while — when did you last see {p['name']}?"
            continue

        try:
            last_date = date.fromisoformat(last["date_value"])
        except (ValueError, TypeError):
            continue

        days_since = (d - last_date).days
        threshold = {"daily": 2, "weekly": 10, "biweekly": 18, "monthly": 35}.get(freq, 999)

        if days_since >= threshold:
            rel = dict(p).get("relationship_type")
            name = p["name"]
            templates = {
                "partner": [
                    f"💜 {days_since} days since your last date with {name}. Worth planning one?",
                    f"💜 {name} — last date was {days_since} days ago.",
                ],
                "family": [
                    f"🧡 When's the last time you really connected with {name}? ({days_since} days)",
                    f"🧡 Quick call or text to {name}?",
                ],
                "friend": [
                    f"💚 {name} — it's been {days_since} days. Reach out?",
                    f"💚 {name} would probably love to hear from you.",
                ],
            }
            pool = templates.get(rel, [f"💜 {name} — been {days_since} days."])
            return random.choice(pool)

    return None


def _me_time_nudge(chat_id, d):
    """Check logged me-time data. Flag if overdue."""
    from modules.me_time import _days_since_metime, _hours_this_week
    days_since = _days_since_metime(chat_id, d)
    hours_this_week = _hours_this_week(chat_id, d)

    if days_since is None:
        # Never logged me-time
        return random.choice([
            "🏠 You haven't logged any me-time yet. Use the Me Time button.",
            "🏠 Personal time matters. Start tracking it — tap Me Time.",
        ])
    if days_since >= 5:
        return random.choice([
            f"🏠 {days_since} days since your last me-time. That's too long.",
            f"🏠 You logged me-time {days_since} days ago. Time to recharge.",
        ])
    if days_since >= 3:
        return "🏠 Been a few days since personal time. Don't let it slide."
    if hours_this_week < 2:
        return "🏠 Only light me-time this week. Try to carve out a real window."
    return None


def _med_nudge(chat_id):
    with db() as conn:
        meds = conn.execute("SELECT * FROM medications WHERE chat_id = ?", (chat_id,)).fetchall()
    if not meds:
        return None
    all_taken = all(m["taken_today"] for m in meds)
    untaken = [m for m in meds if not m["taken_today"]]
    if all_taken:
        return random.choice([
            "💊 All meds handled today. Consistency matters.",
            "💊 Meds done. One less thing.",
            "💊 On top of it. Keep it going.",
        ])
    if untaken:
        return f"💊 {untaken[0]['name']} — still waiting."
    return None


def _deadline_nudge(chat_id, d):
    # Credentials expiring within 30 days
    with db() as conn:
        creds = conn.execute(
            "SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0", (chat_id,)
        ).fetchall()
    for c in creds:
        try:
            delta = days_until(date.fromisoformat(c["expiry_date"]))
            if 7 < delta <= 30:
                return f"🎓 {c['name']} expires in {delta} days. Renewal on your radar?"
        except (ValueError, TypeError):
            pass

    # Bills due within 5 days
    with db() as conn:
        bills = conn.execute(
            "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0", (chat_id,)
        ).fetchall()
    for b in bills:
        if b["due_day"]:
            try:
                due = d.replace(day=min(b["due_day"], 28))
                if due < d:
                    due = due.replace(month=due.month + 1) if due.month < 12 else due.replace(year=due.year + 1, month=1)
                delta = (due - d).days
                if 2 <= delta <= 5:
                    return f"💸 {b['name']} is due in {delta} days."
            except (ValueError, TypeError):
                pass
    return None


def _sleep_conflict(chat_id, d):
    tomorrow = d + timedelta(days=1)
    with db() as conn:
        appts = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND event_date = ? AND done = 0",
            (chat_id, tomorrow.isoformat()),
        ).fetchall()
    for a in appts:
        if dict(a).get("event_time"):
            try:
                hour = int(a["event_time"].split(":")[0])
                if hour < 14:
                    return f"⚠️ Working tonight + \"{a['title']}\" tomorrow at {a['event_time']} — sleep window conflict."
            except (ValueError, TypeError):
                pass
    return None


def _car_nudge(chat_id, d):
    with db() as conn:
        events = conn.execute(
            "SELECT * FROM car_events WHERE chat_id = ? AND done = 0", (chat_id,)
        ).fetchall()
    for e in events:
        try:
            delta = days_until(date.fromisoformat(e["due_date"]))
            if delta <= 14:
                return f"🚗 {e['description']} — due {friendly_date(date.fromisoformat(e['due_date']))}."
        except (ValueError, TypeError):
            pass
    return None


def _note_nudge(chat_id):
    """Surface a random recent note as a reminder."""
    with db() as conn:
        notes = conn.execute(
            "SELECT content FROM notes WHERE chat_id = ? ORDER BY created_at DESC LIMIT 5",
            (chat_id,)
        ).fetchall()
    if not notes:
        return None
    # Pick a random recent note and surface it
    note = random.choice(notes)
    content = note["content"][:60] if note["content"] else ""
    if len(content) > 20:
        return f"📒 From your notes: \"{content}...\""
    return None


def _date_cap_nudge(chat_id, d):
    """Check date activity this week."""
    from datetime import timedelta
    start = d - timedelta(days=(d.weekday() + 1) % 7)
    end = start + timedelta(days=7)
    with db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM partner_dates WHERE chat_id = ? "
            "AND date_value >= ? AND date_value < ? AND recurring = 0",
            (chat_id, start.isoformat(), end.isoformat()),
        ).fetchone()
    n = count["c"] if count else 0
    if n == 0:
        return random.choice([
            "📅 No dates logged this week yet. Anyone worth seeing?",
            "📅 Week's wide open for social plans if you want them.",
        ])
    return None
