# Butler Bot — Today / Tonight view
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""The main home screen. Shift-aware, context-sensitive summary of what matters now."""

from datetime import date, timedelta
from telegram import Update
from telegram.ext import ContextTypes

from database import db, get_user
from helpers import (
    now, today, days_until, urgency_emoji, friendly_date,
    format_money, get_user_shift, get_shift_info, is_payday, next_payday,
    resolve_date, partner_emoji,
)
from keyboards import today_actions_kb


def _dates_this_week(chat_id, d):
    """Count non-recurring partner dates scheduled this week (Sun-Sat)."""
    start = d - timedelta(days=(d.weekday() + 1) % 7)  # Sunday
    end = start + timedelta(days=7)
    with db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM partner_dates WHERE chat_id = ? "
            "AND date_value >= ? AND date_value < ? AND recurring = 0",
            (chat_id, start.isoformat(), end.isoformat())
        ).fetchone()
    return count["c"] if count else 0


async def today_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id if query else update.effective_chat.id

    # Route sub-actions
    if query and query.data:
        parts = query.data.split(":")
        action = parts[1] if len(parts) > 1 else "view"
        if action == "metime":
            from modules.me_time import _show_metime_view
            await _show_metime_view(query, chat_id)
            return
        if action == "suggest":
            await _handle_suggest(query, chat_id)
            return
        if action == "analyze":
            await _handle_analyze(query, chat_id)
            return
        if action == "recovery":
            await _handle_recovery_toggle(query, chat_id)
            return

    user = get_user(chat_id)

    d = today()

    # Shift status
    shift = get_user_shift(chat_id)
    if shift:
        shift_info = get_shift_info(d, shift["anchor"], shift["w1"], shift["w2"], shift["shift_type"])
    else:
        shift_info = "🏠 Off"

    greeting = _greeting(now().hour, shift_info)
    name = user["display_name"] if user else "Boss"
    lines = [f"{greeting}, {name}.", f"📅 {d.strftime('%A, %B %d')}", shift_info, ""]

    # Payday
    if is_payday(d):
        lines.append("💰 IT'S PAYDAY — check your bills below")
        lines.append("")
    else:
        np = next_payday()
        if days_until(np) <= 2:
            lines += [f"💰 Payday {friendly_date(np)}", ""]

    # Meds — only show if there are actually meds configured
    with db() as conn:
        meds = conn.execute("SELECT * FROM medications WHERE chat_id = ?", (chat_id,)).fetchall()
    if meds:  # Only show if meds exist
        untaken = [m["name"] for m in meds if not m["taken_today"]]
        lines.append("💊 Meds: All taken ✅" if not untaken else f"💊 Meds: {', '.join(untaken)} not taken yet")
        lines.append("")

    # Bills due within 3 days
    with db() as conn:
        bills = conn.execute(
            "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0", (chat_id,)
        ).fetchall()
    urgent = []
    for b in bills:
        due, delta = _bill_due_delta(b, d)
        if due and delta <= 3:
            urgent.append((b, delta))
    if urgent:
        lines.append("💸 BILLS DUE SOON:")
        for b, delta in urgent:
            lines.append(f"  {urgency_emoji(delta)} {b['name']} {format_money(b['amount'])} — {friendly_date(d + timedelta(days=delta))}")
        lines.append("")

    # Car / admin due within 30 days
    with db() as conn:
        car_events = conn.execute(
            "SELECT * FROM car_events WHERE chat_id = ? AND done = 0", (chat_id,)
        ).fetchall()
    upcoming_car = []
    for e in car_events:
        try:
            due = date.fromisoformat(e["due_date"])
            delta = days_until(due)
            if delta <= 30:
                upcoming_car.append((e, delta, due))
        except (ValueError, TypeError):
            continue
    if upcoming_car:
        lines.append("🚗 CAR / ADMIN:")
        for e, delta, due in upcoming_car:
            lines.append(f"  {urgency_emoji(delta)} {e['description']} — {friendly_date(due)}")
        lines.append("")

    # Credentials expiring within 60 days
    with db() as conn:
        creds = conn.execute(
            "SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0", (chat_id,)
        ).fetchall()
    upcoming_creds = []
    for c in creds:
        try:
            exp = date.fromisoformat(c["expiry_date"])
            delta = days_until(exp)
            if delta <= 60:
                upcoming_creds.append((c, delta, exp))
        except (ValueError, TypeError):
            continue
    if upcoming_creds:
        lines.append("🎓 CREDENTIALS:")
        for c, delta, exp in upcoming_creds:
            lines.append(f"  {urgency_emoji(delta)} {c['name']} — expires {friendly_date(exp)}")
        lines.append("")

    # Partner dates within 14 days
    with db() as conn:
        partner_dates = conn.execute("""
            SELECT pd.*, p.name as partner_name, p.emoji, p.relationship_type
            FROM partner_dates pd JOIN partners p ON pd.partner_id = p.id
            WHERE pd.chat_id = ?
        """, (chat_id,)).fetchall()
    upcoming_partner = []
    for pd_row in partner_dates:
        target = resolve_date(pd_row["date_value"], d)
        delta = days_until(target) if target else 999
        if target and 0 <= delta <= 14:
            upcoming_partner.append((pd_row, delta))
    if upcoming_partner:
        lines.append("💜 COMING UP:")
        for pd_row, delta in upcoming_partner:
            emoji = partner_emoji(pd_row)
            label = pd_row["label"] or pd_row["date_type"]
            lines.append(f"  {emoji} {pd_row['partner_name']} — {label} {friendly_date(d + timedelta(days=delta))}")
        lines.append("")

    # Appointments within 7 days
    from modules.appointments import get_upcoming_appointments, CATEGORY_EMOJI
    upcoming_appts = get_upcoming_appointments(chat_id, days_ahead=7)
    if upcoming_appts:
        lines.append("📅 APPOINTMENTS:")
        for a in upcoming_appts:
            event_date = date.fromisoformat(a["event_date"])
            delta = days_until(event_date)
            time_str = f" at {a['event_time']}" if dict(a).get("event_time") else ""
            cat_emoji = CATEGORY_EMOJI.get(dict(a).get("category") or "other", "📅")
            lines.append(f"  {urgency_emoji(delta)} {cat_emoji} {a['title']}{time_str} — {friendly_date(event_date)}")
        lines.append("")

    # Today's notes
    with db() as conn:
        today_notes = conn.execute(
            "SELECT * FROM notes WHERE chat_id = ? AND date(created_at) = ? ORDER BY id DESC LIMIT 3",
            (chat_id, d.isoformat())
        ).fetchall()
    if today_notes:
        lines.append("📒 TODAY'S NOTES:")
        for n in today_notes:
            lines.append(f"  • {n['content'][:60]}")
        lines.append("")

    # Suggestions
    from modules.suggestions import get_suggestions
    suggestions = get_suggestions(chat_id, "afternoon")
    if suggestions:
        lines.append("")
        lines.append("💡 SUGGESTIONS:")
        for s in suggestions:
            lines.append(f"  {s}")

    # Date budget display
    dates_count = _dates_this_week(chat_id, d)
    if dates_count > 0 or shift:
        lines.append(f"")
        lines.append(f"📅 Dates this week: {dates_count}/2")

    if len(lines) <= 4:
        lines.append("Nothing urgent. Enjoy your day. 🫡")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n[...truncated — tap Menu to see more]"
    if query:
        try:
            await query.edit_message_text(text, reply_markup=today_actions_kb())
        except Exception:
            await query.message.reply_text(text, reply_markup=today_actions_kb())
    else:
        await update.message.reply_text(text, reply_markup=today_actions_kb())


# ── Private helpers ──────────────────────────────────────

def _greeting(hour: int, shift_info: str = "") -> str:
    """Shift-aware greeting. Checks shift status before falling back to hour-based."""
    if shift_info and "Post-shift recovery" in shift_info:
        return "Recovery day"
    if shift_info and "Work" in shift_info:
        return "Work tonight"
    if hour < 6:    return "Late night"
    if hour < 12:   return "Good morning"
    if hour < 17:   return "Good afternoon"
    if hour < 21:   return "Good evening"
    return "Night owl hours"


def _bill_due_delta(bill, d):
    """Returns (due_date, days_delta) or (None, 999)."""
    if bill["due_day"]:
        due = d.replace(day=min(bill["due_day"], 28))
        if due < d:
            due = (due.replace(month=due.month + 1) if due.month < 12
                   else due.replace(year=due.year + 1, month=1))
        return due, (due - d).days
    if bill["due_date"]:
        due = date.fromisoformat(bill["due_date"])
        return due, (due - d).days
    return None, 999





# ── Me Time, Suggestions, Analyze handlers ──────────────────────

async def _handle_metime(query, chat_id):
    """Show me-time ideas based on current shift status."""
    from helpers import get_user_shift, get_shift_info, is_working, now
    d = today()
    shift = get_user_shift(chat_id)
    current_hour = now().hour
    worked_yesterday = is_working(chat_id, d - timedelta(days=1))
    working_today = is_working(chat_id, d)
    is_transition = worked_yesterday and not working_today

    if shift and working_today:
        lines = [
            "🏥 You're working today — me-time will have to wait.",
            "",
            "After your shift:",
            "  😴 Sleep (protect your window)",
            "  🎵 Decompress with music",
            "  📱 Doomscroll for 15 min max, then lights out",
        ]
    elif is_transition:
        # Find next work day for window estimate
        next_work = None
        if shift:
            for i in range(1, 8):
                check = d + timedelta(days=i)
                if is_working(chat_id, check):
                    next_work = check
                    break
        lines = [
            "🔄 Transition day — your body is adjusting schedules.",
            "",
            "Good windows:",
            "  😴 Rest 1–3 hours after waking",
            "  🚶 Errands between 5 PM and 9 PM if needed",
            "  🎵 Low-key activities — nothing demanding",
            "  📱 Light screen time, avoid heavy decisions",
        ]
        if next_work:
            lines.append(f"  📅 Next shift: {next_work.strftime('%A')} — start adjusting tonight")
    else:
        # Find next work day
        next_work = None
        if shift:
            for i in range(1, 8):
                check = d + timedelta(days=i)
                if is_working(chat_id, check):
                    next_work = check
                    break
        if next_work:
            until = f"next shift ({next_work.strftime('%A')})"
        else:
            until = "your next shift"

        lines = [
            f"🏠 ME TIME — You're off until {until}.",
            "",
            "Ideas:",
            f"  🎮 Gaming window: now – whenever",
            "  😴 Rest (post-shift recovery)" if shift else "  😴 Rest & recharge",
            "  🎵 Music / creative time",
            "  🚶 Get outside for 15+ min",
            "  📅 Free for a date tonight?",
        ]

    await query.edit_message_text("\n".join(lines), reply_markup=today_actions_kb())


async def _handle_suggest(query, chat_id):
    """Show contextual suggestions."""
    from modules.suggestions import get_suggestions
    current_hour = now().hour
    time_of_day = "afternoon" if current_hour < 18 else "evening"
    suggestions = get_suggestions(chat_id, time_of_day)

    if suggestions:
        lines = ["💡 SUGGESTIONS", ""]
        for s in suggestions:
            lines.append(f"  {s}")
    else:
        lines = ["💡 No suggestions right now. You're on top of things. 🫡"]

    await query.edit_message_text("\n".join(lines), reply_markup=today_actions_kb())


async def _handle_recovery_toggle(query, chat_id):
    """Flip the Minimum-Viable-Day toggle.

    On: tighten the bot — only the bare-bones tonight (meds, water, one nice thing).
    Off: back to full mode.
    """
    from modules.wellness import is_recovery_mode, set_recovery_mode
    currently_on = is_recovery_mode(chat_id)
    set_recovery_mode(chat_id, not currently_on)
    if not currently_on:
        await query.edit_message_text(
            "🌱 Recovery mode on.\n\n"
            "Tonight: meds, water, one nice thing.\n"
            "Everything else can wait. I've got you.",
            reply_markup=today_actions_kb(),
        )
    else:
        await query.edit_message_text(
            "✅ Back to full mode. Welcome back.",
            reply_markup=today_actions_kb(),
        )


async def _handle_analyze(query, chat_id):
    """Quick personal status summary."""
    d = today()
    lines = ["📊 QUICK STATUS", ""]

    # Meds
    with db() as conn:
        meds = conn.execute("SELECT * FROM medications WHERE chat_id = ?", (chat_id,)).fetchall()
    if meds:
        taken = sum(1 for m in meds if m["taken_today"])
        lines.append(f"💊 Meds: {taken}/{len(meds)} taken today")

    # Bills
    with db() as conn:
        bills = conn.execute("SELECT * FROM bills WHERE chat_id = ?", (chat_id,)).fetchall()
    if bills:
        unpaid = [b for b in bills if not b["paid_this_cycle"]]
        total = sum((b["amount"] or 0) for b in unpaid)
        lines.append(f"💸 Bills: {len(unpaid)} unpaid ({format_money(total)})")

    # Me-time
    from modules.me_time import _days_since_metime, _hours_this_week
    me_days_since = _days_since_metime(chat_id, d)
    me_hours_week = _hours_this_week(chat_id, d)
    if me_days_since is None:
        lines.append("🏠 Me time: none logged yet")
    elif me_days_since == 0:
        lines.append(f"🏠 Me time: today ({me_hours_week:.1f} hrs this week)")
    else:
        lines.append(f"🏠 Me time: {me_days_since}d ago ({me_hours_week:.1f} hrs this week)")

    # Dates this week
    dates_count = _dates_this_week(chat_id, d)
    lines.append(f"📅 Dates this week: {dates_count}")

    # Credentials expiring within 90 days
    with db() as conn:
        creds = conn.execute(
            "SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0", (chat_id,)
        ).fetchall()
    expiring = []
    for c in creds:
        try:
            if days_until(date.fromisoformat(c["expiry_date"])) <= 90:
                expiring.append(c)
        except (ValueError, TypeError):
            continue
    if expiring:
        lines.append(f"🎓 Credentials expiring soon: {len(expiring)}")

    # Car items due within 60 days
    with db() as conn:
        car_events = conn.execute(
            "SELECT * FROM car_events WHERE chat_id = ? AND done = 0", (chat_id,)
        ).fetchall()
    car_due = []
    for e in car_events:
        try:
            if days_until(date.fromisoformat(e["due_date"])) <= 60:
                car_due.append(e)
        except (ValueError, TypeError):
            continue
    if car_due:
        lines.append(f"🚗 Car items due: {len(car_due)}")

    # Upcoming appointments (next 3)
    from modules.appointments import get_upcoming_appointments, CATEGORY_EMOJI
    upcoming = get_upcoming_appointments(chat_id, days_ahead=14)
    if upcoming:
        lines.append("")
        lines.append("📅 Upcoming:")
        for a in upcoming[:3]:
            event_date = date.fromisoformat(a["event_date"])
            cat_emoji = CATEGORY_EMOJI.get(dict(a).get("category") or "other", "📅")
            lines.append(f"  {cat_emoji} {a['title']} — {friendly_date(event_date)}")

    if len(lines) <= 2:
        lines.append("Nothing tracked yet. Add items from the menu.")

    await query.edit_message_text("\n".join(lines), reply_markup=today_actions_kb())
