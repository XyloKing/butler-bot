# Butler Bot — Week View
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""ASCII-style calendar showing the week at a glance. Sunday-first layout."""

from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import db
from helpers import today, is_work_day, get_user_shift, ascii_week_calendar, days_until
from keyboards import back_to_menu_kb


async def week_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "view"

    if action == "view":
        offset = int(parts[2]) if len(parts) > 2 else 0
        await _show_week(query, chat_id, offset)
    elif action == "next":
        current = int(parts[2]) if len(parts) > 2 else 0
        await _show_week(query, chat_id, current + 7)
    elif action == "prev":
        current = int(parts[2]) if len(parts) > 2 else 0
        await _show_week(query, chat_id, current - 7)


async def _show_week(query, chat_id, offset=0):
    d = today() + timedelta(days=offset)
    # Sunday-first: find the most recent Sunday
    sun_offset = (d.weekday() + 1) % 7
    start = d - timedelta(days=sun_offset)

    # Build work days list
    shift = get_user_shift(chat_id)
    work_days = []
    if shift:
        for i in range(7):
            check = start + timedelta(days=i)
            if is_work_day(check, shift["anchor"], shift["w1"], shift["w2"]):
                work_days.append(check)

    # Gather events for each day
    events: dict[date, list[str]] = {}
    end = start + timedelta(days=7)

    with db() as conn:
        # Bills
        bills = conn.execute(
            "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0", (chat_id,)
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
            if check.weekday() == 4:
                events.setdefault(check, []).append("💰 PAYDAY")

        # Car events
        for e in conn.execute("SELECT * FROM car_events WHERE chat_id = ? AND done = 0", (chat_id,)).fetchall():
            due = date.fromisoformat(e["due_date"])
            if start <= due < end:
                events.setdefault(due, []).append(f"🚗 {e['description']}")

        # Partner dates
        pdates = conn.execute("""
            SELECT pd.*, p.name as partner_name, p.emoji, p.relationship_type
            FROM partner_dates pd JOIN partners p ON pd.partner_id = p.id
            WHERE pd.chat_id = ?
        """, (chat_id,)).fetchall()
        for pd_row in pdates:
            target = _resolve_date(pd_row["date_value"], start)
            if target and start <= target < end:
                emoji = pd_row.get("emoji") or "💜"
                label = pd_row.get("label") or pd_row["date_type"]
                events.setdefault(target, []).append(f"{emoji} {pd_row['partner_name']} — {label}")

        # Credentials
        for c in conn.execute("SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0", (chat_id,)).fetchall():
            exp = date.fromisoformat(c["expiry_date"])
            if start <= exp < end:
                events.setdefault(exp, []).append(f"🎓 {c['name']} EXPIRES")

        # Appointments
        appts = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND done = 0 AND event_date >= ? AND event_date < ?",
            (chat_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        from modules.appointments import CATEGORY_EMOJI
        for a in appts:
            adate = date.fromisoformat(a["event_date"])
            time_str = f" {a['event_time']}" if a["event_time"] else ""
            cat_emoji = CATEGORY_EMOJI.get(a.get("category") or "other", "📅")
            events.setdefault(adate, []).append(f"{cat_emoji} {a['title']}{time_str}")

    cal = ascii_week_calendar(start, work_days, events)
    text = f"📆 Week of {start.strftime('%B %d')}\n\n```\n{cal}\n```"

    nav_row = [
        InlineKeyboardButton("◀ Prev Week", callback_data=f"week:prev:{offset}"),
        InlineKeyboardButton("▶ Next Week", callback_data=f"week:next:{offset}"),
    ]
    rows = [nav_row]
    if offset != 0:
        rows.append([InlineKeyboardButton("📍 This Week", callback_data="week:view:0")])
    rows.append([
        InlineKeyboardButton("📅 Alter Schedule", callback_data="alter:start"),
        InlineKeyboardButton("⬅️ Menu", callback_data="menu:main"),
    ])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")


def _resolve_date(date_value, start):
    """Resolve MM-DD or ISO date string to a date object."""
    try:
        if len(date_value) == 5:
            for year in [start.year, start.year + 1]:
                target = date(year, int(date_value[:2]), int(date_value[3:]))
                if target >= start:
                    return target
        else:
            return date.fromisoformat(date_value)
    except (ValueError, TypeError):
        return None
