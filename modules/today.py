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
)
from keyboards import today_actions_kb


async def today_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id if query else update.effective_chat.id
    user = get_user(chat_id)

    d = today()
    greeting = _greeting(now().hour)

    # Shift status
    shift = get_user_shift(chat_id)
    if shift:
        shift_info = get_shift_info(d, shift["anchor"], shift["w1"], shift["w2"], shift["shift_type"])
    else:
        shift_info = "🏠 Off"

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

    # Meds
    with db() as conn:
        meds = conn.execute("SELECT * FROM medications WHERE chat_id = ?", (chat_id,)).fetchall()
    if meds:
        untaken = [m["name"] for m in meds if not m["taken_today"]]
        lines.append("💊 Meds: All taken ✅" if not untaken else f"💊 Meds: {', '.join(untaken)} NOT TAKEN ⚠️")
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
    upcoming_car = [(e, days_until(date.fromisoformat(e["due_date"]))) for e in car_events]
    upcoming_car = [(e, d) for e, d in upcoming_car if d <= 30]
    if upcoming_car:
        lines.append("🚗 CAR / ADMIN:")
        for e, delta in upcoming_car:
            lines.append(f"  {urgency_emoji(delta)} {e['description']} — {friendly_date(date.fromisoformat(e['due_date']))}")
        lines.append("")

    # Credentials expiring within 60 days
    with db() as conn:
        creds = conn.execute(
            "SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0", (chat_id,)
        ).fetchall()
    upcoming_creds = [(c, days_until(date.fromisoformat(c["expiry_date"]))) for c in creds]
    upcoming_creds = [(c, d) for c, d in upcoming_creds if d <= 60]
    if upcoming_creds:
        lines.append("🎓 CREDENTIALS:")
        for c, delta in upcoming_creds:
            lines.append(f"  {urgency_emoji(delta)} {c['name']} — expires {friendly_date(date.fromisoformat(c['expiry_date']))}")
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
        target, delta = _resolve_partner_date(pd_row["date_value"], d)
        if target and 0 <= delta <= 14:
            upcoming_partner.append((pd_row, delta))
    if upcoming_partner:
        lines.append("💜 COMING UP:")
        for pd_row, delta in upcoming_partner:
            emoji = _partner_emoji(pd_row)
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
            time_str = f" at {a['event_time']}" if a.get("event_time") else ""
            cat_emoji = CATEGORY_EMOJI.get(a.get("category") or "other", "📅")
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

    if len(lines) <= 4:
        lines.append("Nothing urgent. Enjoy your day. 🫡")

    text = "\n".join(lines)
    if query:
        try:
            await query.edit_message_text(text, reply_markup=today_actions_kb())
        except Exception:
            await query.message.reply_text(text, reply_markup=today_actions_kb())
    else:
        await update.message.reply_text(text, reply_markup=today_actions_kb())


# ── Private helpers ──────────────────────────────────────

def _greeting(hour: int) -> str:
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


def _resolve_partner_date(date_value, d):
    """Resolve a partner date (MM-DD or ISO) to (target_date, delta)."""
    try:
        if len(date_value) == 5:  # MM-DD recurring
            this_year = date(d.year, int(date_value[:2]), int(date_value[3:]))
            if this_year < d:
                this_year = date(d.year + 1, int(date_value[:2]), int(date_value[3:]))
            return this_year, days_until(this_year)
        else:
            target = date.fromisoformat(date_value)
            return target, days_until(target)
    except (ValueError, TypeError):
        return None, 999


def _partner_emoji(pd_row):
    """Get display emoji for a partner date row."""
    from keyboards import RELATIONSHIP_TYPES
    rel = pd_row.get("relationship_type")
    if rel and rel in RELATIONSHIP_TYPES:
        return RELATIONSHIP_TYPES[rel][0]
    return pd_row.get("emoji") or "💜"
