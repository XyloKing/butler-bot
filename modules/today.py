"""
📅 Today / Tonight — the main home screen view.
Shift-aware, context-sensitive summary of what matters RIGHT NOW.
"""
import json
from datetime import date, timedelta
from telegram import Update
from telegram.ext import ContextTypes

from database import db, get_user
from helpers import (
    now, today, days_until, urgency_emoji, friendly_date,
    format_money, is_work_day, get_shift_info, is_payday, next_payday,
)
from keyboards import today_actions_kb


async def today_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Build and send the Today/Tonight summary."""
    query = update.callback_query
    if query:
        await query.answer()
    chat_id = (query or update).message.chat_id if not query else query.message.chat_id
    user = get_user(chat_id)

    d = today()
    current_hour = now().hour
    greeting = _get_greeting(current_hour)

    # Get shift info
    shift_info = "🏠 Off"
    with db() as conn:
        shift_row = conn.execute(
            "SELECT * FROM shifts WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
            (chat_id,)
        ).fetchone()
    if shift_row and shift_row["week1_days"]:
        w1 = json.loads(shift_row["week1_days"])
        w2 = json.loads(shift_row["week2_days"] or "[]") or w1
        try:
            anchor = shift_row["anchor_date"] or "2026-03-30"
        except (IndexError, KeyError):
            anchor = "2026-03-30"
        try:
            stype = shift_row["shift_type"] or "7p-7a"
        except (IndexError, KeyError):
            stype = "7p-7a"
        shift_info = get_shift_info(d, anchor, w1, w2, stype)

    name = user["display_name"] if user else "Boss"
    lines = [
        f"{greeting}, {name}.",
        f"📅 {d.strftime('%A, %B %d')}",
        f"{shift_info}",
        "",
    ]

    # ── Payday Check ─────────────────────────────────
    if is_payday(d):
        lines.append("💰 IT'S PAYDAY — check your bills below")
        lines.append("")
    else:
        np = next_payday()
        days_to_pay = days_until(np)
        if days_to_pay <= 2:
            lines.append(f"💰 Payday {friendly_date(np)}")
            lines.append("")

    # ── Medications ──────────────────────────────────
    with db() as conn:
        meds = conn.execute(
            "SELECT * FROM medications WHERE chat_id = ?", (chat_id,)
        ).fetchall()
    if meds:
        all_taken = all(m["taken_today"] for m in meds)
        if all_taken:
            lines.append("💊 Meds: All taken ✅")
        else:
            untaken = [m["name"] for m in meds if not m["taken_today"]]
            lines.append(f"💊 Meds: {', '.join(untaken)} NOT TAKEN ⚠️")
        lines.append("")

    # ── Bills Due Soon ───────────────────────────────
    with db() as conn:
        bills = conn.execute(
            "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0",
            (chat_id,)
        ).fetchall()
    urgent_bills = []
    for b in bills:
        if b["due_day"]:
            # Check if due within 3 days
            due = d.replace(day=min(b["due_day"], 28))
            if due < d:
                due = (due.replace(month=due.month + 1) if due.month < 12
                       else due.replace(year=due.year + 1, month=1))
            delta = (due - d).days
            if delta <= 3:
                urgent_bills.append((b, delta))
        elif b["due_date"]:
            due = date.fromisoformat(b["due_date"])
            delta = (due - d).days
            if delta <= 3:
                urgent_bills.append((b, delta))

    if urgent_bills:
        lines.append("💸 BILLS DUE SOON:")
        for b, delta in urgent_bills:
            emoji = urgency_emoji(delta)
            amt = format_money(b["amount"])
            lines.append(f"  {emoji} {b['name']} {amt} — {friendly_date(d + timedelta(days=delta))}")
        lines.append("")

    # ── Car / Admin Due Soon ─────────────────────────
    with db() as conn:
        car_events = conn.execute(
            "SELECT * FROM car_events WHERE chat_id = ? AND done = 0",
            (chat_id,)
        ).fetchall()
    upcoming_car = []
    for e in car_events:
        due = date.fromisoformat(e["due_date"])
        delta = days_until(due)
        if delta <= 30:
            upcoming_car.append((e, delta))

    if upcoming_car:
        lines.append("🚗 CAR / ADMIN:")
        for e, delta in upcoming_car:
            emoji = urgency_emoji(delta)
            lines.append(f"  {emoji} {e['description']} — {friendly_date(date.fromisoformat(e['due_date']))}")
        lines.append("")

    # ── Credentials Due Soon ─────────────────────────
    with db() as conn:
        creds = conn.execute(
            "SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0",
            (chat_id,)
        ).fetchall()
    upcoming_creds = []
    for c in creds:
        exp = date.fromisoformat(c["expiry_date"])
        delta = days_until(exp)
        if delta <= 60:
            upcoming_creds.append((c, delta))

    if upcoming_creds:
        lines.append("🎓 CREDENTIALS:")
        for c, delta in upcoming_creds:
            emoji = urgency_emoji(delta)
            lines.append(f"  {emoji} {c['name']} — expires {friendly_date(date.fromisoformat(c['expiry_date']))}")
        lines.append("")

    # ── Partner Dates Coming Up ──────────────────────
    with db() as conn:
        partner_dates = conn.execute("""
            SELECT pd.*, p.name as partner_name, p.emoji
            FROM partner_dates pd
            JOIN partners p ON pd.partner_id = p.id
            WHERE pd.chat_id = ?
        """, (chat_id,)).fetchall()

    upcoming_partner = []
    for pd_row in partner_dates:
        dv = pd_row["date_value"]
        if len(dv) == 5:  # MM-DD recurring
            this_year = date(d.year, int(dv[:2]), int(dv[3:]))
            if this_year < d:
                this_year = date(d.year + 1, int(dv[:2]), int(dv[3:]))
            delta = days_until(this_year)
        else:
            target = date.fromisoformat(dv)
            delta = days_until(target)

        if 0 <= delta <= 14:
            upcoming_partner.append((pd_row, delta))

    if upcoming_partner:
        lines.append("💜 COMING UP:")
        for pd_row, delta in upcoming_partner:
            emoji = pd_row["emoji"] or "💜"
            label = pd_row["label"] or pd_row["date_type"]
            lines.append(f"  {emoji} {pd_row['partner_name']} — {label} {friendly_date(d + timedelta(days=delta))}")
        lines.append("")

    # ── Notes for today ──────────────────────────────
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
        await query.edit_message_text(text, reply_markup=today_actions_kb())
    else:
        await update.message.reply_text(text, reply_markup=today_actions_kb())


def _get_greeting(hour: int) -> str:
    if hour < 6:
        return "Late night"
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    if hour < 21:
        return "Good evening"
    return "Night owl hours"
