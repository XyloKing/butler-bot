"""
📆 Week View module.
ASCII-style calendar showing the week at a glance.
"""
import json
from datetime import date, timedelta
from telegram import Update
from telegram.ext import ContextTypes

from database import db
from helpers import today, is_work_day, ascii_week_calendar, days_until
from keyboards import back_to_menu_kb


async def week_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route week:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "view"

    if action == "view":
        await _show_week(query, chat_id, offset=0)
    elif action == "next":
        await _show_week(query, chat_id, offset=7)
    elif action == "prev":
        await _show_week(query, chat_id, offset=-7)


async def _show_week(query, chat_id, offset=0):
    d = today() + timedelta(days=offset)
    # Start from Monday of this week
    start = d - timedelta(days=d.weekday())

    # Get shift schedule
    with db() as conn:
        shift = conn.execute(
            "SELECT * FROM shifts WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
            (chat_id,)
        ).fetchone()

    work_days = []
    if shift and shift["week1_days"]:
        w1 = json.loads(shift["week1_days"])
        w2 = json.loads(shift["week2_days"] or "[]") or w1
        try:
            anchor = shift["anchor_date"] or "2026-03-30"
        except (IndexError, KeyError):
            anchor = "2026-03-30"
        for i in range(7):
            check = start + timedelta(days=i)
            if is_work_day(check, anchor, w1, w2):
                work_days.append(check)

    # Gather events for each day
    events: dict[date, list[str]] = {}

    with db() as conn:
        # Bills due this week
        bills = conn.execute(
            "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0",
            (chat_id,)
        ).fetchall()
        for b in bills:
            if b["due_day"]:
                for i in range(7):
                    check = start + timedelta(days=i)
                    if check.day == b["due_day"]:
                        events.setdefault(check, []).append(f"💸 {b['name']}")

        # Payday (Fridays)
        for i in range(7):
            check = start + timedelta(days=i)
            if check.weekday() == 4:  # Friday
                events.setdefault(check, []).append("💰 PAYDAY")

        # Car events
        car = conn.execute(
            "SELECT * FROM car_events WHERE chat_id = ? AND done = 0", (chat_id,)
        ).fetchall()
        for e in car:
            due = date.fromisoformat(e["due_date"])
            if start <= due < start + timedelta(days=7):
                events.setdefault(due, []).append(f"🚗 {e['description']}")

        # Partner dates
        pdates = conn.execute("""
            SELECT pd.*, p.name as partner_name, p.emoji
            FROM partner_dates pd
            JOIN partners p ON pd.partner_id = p.id
            WHERE pd.chat_id = ?
        """, (chat_id,)).fetchall()
        for pd_row in pdates:
            dv = pd_row["date_value"]
            try:
                if len(dv) == 5:  # MM-DD
                    for year in [start.year, start.year + 1]:
                        target = date(year, int(dv[:2]), int(dv[3:]))
                        if start <= target < start + timedelta(days=7):
                            emoji = pd_row["emoji"] or "💜"
                            try:
                                label = pd_row["label"] or pd_row["date_type"]
                            except (IndexError, KeyError):
                                label = pd_row["date_type"]
                            events.setdefault(target, []).append(
                                f"{emoji} {pd_row['partner_name']} — {label}"
                            )
                else:
                    target = date.fromisoformat(dv)
                    if start <= target < start + timedelta(days=7):
                        emoji = pd_row["emoji"] or "💜"
                        try:
                            label = pd_row["label"] or pd_row["date_type"]
                        except (IndexError, KeyError):
                            label = pd_row["date_type"]
                        events.setdefault(target, []).append(
                            f"{emoji} {pd_row['partner_name']} — {label}"
                        )
            except (ValueError, TypeError):
                pass

        # Credential expiries
        creds = conn.execute(
            "SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0", (chat_id,)
        ).fetchall()
        for c in creds:
            exp = date.fromisoformat(c["expiry_date"])
            if start <= exp < start + timedelta(days=7):
                events.setdefault(exp, []).append(f"🎓 {c['name']} EXPIRES")

        # Appointments
        appts = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND done = 0 "
            "AND event_date >= ? AND event_date < ?",
            (chat_id, start.isoformat(), (start + timedelta(days=7)).isoformat()),
        ).fetchall()
        for a in appts:
            adate = date.fromisoformat(a["event_date"])
            time_str = f" {a['event_time']}" if a["event_time"] else ""
            events.setdefault(adate, []).append(f"📅 {a['title']}{time_str}")

    # Build calendar
    cal = ascii_week_calendar(start, work_days, events)

    week_label = f"Week of {start.strftime('%B %d')}"
    text = f"📆 {week_label}\n\n```\n{cal}\n```"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    nav_row = [
        InlineKeyboardButton("◀ Prev Week", callback_data="week:prev"),
        InlineKeyboardButton("▶ Next Week", callback_data="week:next"),
    ]
    kb = InlineKeyboardMarkup([
        nav_row,
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")],
    ])

    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
