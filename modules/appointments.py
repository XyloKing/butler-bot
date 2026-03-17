"""
📅 Appointments / Events module.
Add, view, edit, delete appointments with date parsing.
Shows on week view + today view + scheduler reminders.
"""
import re
from datetime import datetime, date, timedelta
from telegram import Update
from telegram.ext import ContextTypes

from database import db
from helpers import today, days_until, friendly_date, urgency_emoji
from keyboards import back_to_menu_kb

AWAITING_APPT_TITLE = "appt_title"
AWAITING_APPT_DATE = "appt_date"
AWAITING_APPT_TIME = "appt_time"
AWAITING_APPT_NOTES = "appt_notes"


# ═══════════════════════════════════════════════════════
# CALLBACK ROUTER
# ═══════════════════════════════════════════════════════

async def appts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all appts:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "view"

    if action == "view":
        await _show_appts_list(query, chat_id)

    elif action == "add":
        context.user_data["awaiting"] = AWAITING_APPT_TITLE
        await query.edit_message_text(
            "📅 What's the appointment or event?\n"
            "(e.g. 'Dentist', 'Railway trial ends', 'Dinner with Sam')"
        )

    elif action == "detail":
        appt_id = int(parts[2]) if len(parts) > 2 else None
        await _show_appt_detail(query, chat_id, appt_id)

    elif action == "done":
        appt_id = int(parts[2])
        with db() as conn:
            conn.execute(
                "UPDATE appointments SET done = 1 WHERE id = ? AND chat_id = ?",
                (appt_id, chat_id),
            )
        await query.edit_message_text("✅ Marked done.")
        await _show_appts_list(query, chat_id, send_new=True)

    elif action == "undone":
        appt_id = int(parts[2])
        with db() as conn:
            conn.execute(
                "UPDATE appointments SET done = 0 WHERE id = ? AND chat_id = ?",
                (appt_id, chat_id),
            )
        await query.edit_message_text("↩️ Reopened.")
        await _show_appts_list(query, chat_id, send_new=True)

    elif action == "delete":
        appt_id = int(parts[2])
        from keyboards import confirm_delete_kb
        with db() as conn:
            appt = conn.execute(
                "SELECT * FROM appointments WHERE id = ? AND chat_id = ?",
                (appt_id, chat_id)
            ).fetchone()
        if appt:
            await query.edit_message_text(
                f"🗑 Delete \"{appt['title']}\"?",
                reply_markup=confirm_delete_kb("appts", appt_id),
            )

    elif action == "confirm_delete":
        appt_id = int(parts[2])
        with db() as conn:
            conn.execute(
                "DELETE FROM appointments WHERE id = ? AND chat_id = ?",
                (appt_id, chat_id),
            )
        await query.edit_message_text("🗑 Deleted.")
        await _show_appts_list(query, chat_id, send_new=True)

    elif action == "editfield":
        appt_id = int(parts[2])
        field = parts[3]
        from modules.field_editor import start_field_edit
        await start_field_edit(update, context, "appts", appt_id, field)

    elif action == "skip_time":
        # User chose to skip adding a time
        await _save_appointment(update, context, event_time=None)

    elif action == "skip_notes":
        # User chose to skip adding notes
        await _save_appointment_final(update, context, notes=None)


# ═══════════════════════════════════════════════════════
# LIST & DETAIL VIEWS
# ═══════════════════════════════════════════════════════

async def _show_appts_list(query, chat_id, send_new=False):
    """Show all appointments for this user."""
    appts = _get_appointments(chat_id)
    from keyboards import appts_list_kb

    if not appts:
        text = "📅 No appointments yet.\n\nTap below to add one."
        kb = appts_list_kb([])
    else:
        text = f"📅 APPOINTMENTS ({len(appts)})\n\nTap to view:"
        kb = appts_list_kb(appts)

    if send_new:
        await query.message.reply_text(text, reply_markup=kb)
    else:
        await query.edit_message_text(text, reply_markup=kb)


async def _show_appt_detail(query, chat_id, appt_id):
    """Show detail view for one appointment."""
    with db() as conn:
        appt = conn.execute(
            "SELECT * FROM appointments WHERE id = ? AND chat_id = ?",
            (appt_id, chat_id)
        ).fetchone()

    if not appt:
        await query.edit_message_text("Appointment not found.", reply_markup=back_to_menu_kb())
        return

    from keyboards import appt_detail_kb

    done_str = "✅ Done" if appt["done"] else "⬜ Pending"
    event_date = date.fromisoformat(appt["event_date"])
    delta = days_until(event_date)
    urg = urgency_emoji(delta)

    lines = [
        f"📅 {appt['title']}",
        f"Date: {urg} {appt['event_date']} — {friendly_date(event_date)}",
    ]
    if appt["event_time"]:
        lines.append(f"Time: {appt['event_time']}")
    lines.append(f"Status: {done_str}")
    if appt["notes"]:
        lines.append(f"\n📒 {appt['notes']}")

    text = "\n".join(lines)
    await query.edit_message_text(text, reply_markup=appt_detail_kb(appt_id, appt["done"]))


# ═══════════════════════════════════════════════════════
# ADD FLOW — multi-step: title → date → time (optional) → notes (optional)
# ═══════════════════════════════════════════════════════

async def handle_appt_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input during appointment creation. Returns True if consumed."""
    awaiting = context.user_data.get("awaiting")

    if awaiting == AWAITING_APPT_TITLE:
        return await _handle_title(update, context)
    elif awaiting == AWAITING_APPT_DATE:
        return await _handle_date(update, context)
    elif awaiting == AWAITING_APPT_TIME:
        return await _handle_time(update, context)
    elif awaiting == AWAITING_APPT_NOTES:
        return await _handle_notes(update, context)

    return False


async def _handle_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Step 1: Got the title, now ask for date."""
    text = update.message.text.strip()
    context.user_data["appt_title"] = text
    context.user_data["awaiting"] = AWAITING_APPT_DATE
    await update.message.reply_text(
        f"📅 Got it: \"{text}\"\n\n"
        "When is it?\n"
        "(e.g. 'March 29', '2026-04-15', 'April 3 2026')"
    )
    return True


async def _handle_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Step 2: Got the date, now ask for time (optional)."""
    text = update.message.text.strip()
    parsed = _parse_date_loosely(text)

    # Validate it's a real date
    try:
        date.fromisoformat(parsed)
    except (ValueError, TypeError):
        await update.message.reply_text(
            "Couldn't understand that date. Try:\n"
            "• March 29\n"
            "• 2026-04-15\n"
            "• April 3 2026"
        )
        return True

    context.user_data["appt_date"] = parsed
    context.user_data["awaiting"] = AWAITING_APPT_TIME

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ No Time / All Day", callback_data="appts:skip_time")],
    ])
    await update.message.reply_text(
        f"📅 Date: {parsed}\n\n"
        "What time? (e.g. '2pm', '14:00', '9:30am')\n"
        "Or tap below to skip.",
        reply_markup=kb,
    )
    return True


async def _handle_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Step 3: Got the time (or skip), now ask for notes (optional)."""
    text = update.message.text.strip()
    parsed_time = _parse_time_loosely(text)
    await _save_appointment(update, context, event_time=parsed_time)
    return True


async def _save_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE, event_time=None):
    """After date+time collected, ask for notes."""
    context.user_data["appt_time"] = event_time
    context.user_data["awaiting"] = AWAITING_APPT_NOTES

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Skip Notes", callback_data="appts:skip_notes")],
    ])

    title = context.user_data.get("appt_title", "")
    appt_date = context.user_data.get("appt_date", "")
    time_str = f" at {event_time}" if event_time else ""

    # Use query if this came from a button press
    query = update.callback_query
    if query:
        await query.edit_message_text(
            f"📅 {title}\n"
            f"Date: {appt_date}{time_str}\n\n"
            "Any notes? (description, location, etc.)\n"
            "Or tap below to skip.",
            reply_markup=kb,
        )
    else:
        await update.message.reply_text(
            f"📅 {title}\n"
            f"Date: {appt_date}{time_str}\n\n"
            "Any notes? (description, location, etc.)\n"
            "Or tap below to skip.",
            reply_markup=kb,
        )


async def _handle_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Step 4: Got notes, save everything."""
    text = update.message.text.strip()
    await _save_appointment_final(update, context, notes=text)
    return True


async def _save_appointment_final(update: Update, context: ContextTypes.DEFAULT_TYPE, notes=None):
    """Save the appointment to the database."""
    query = update.callback_query
    chat_id = query.message.chat_id if query else update.effective_chat.id

    title = context.user_data.pop("appt_title", "Untitled")
    appt_date = context.user_data.pop("appt_date", today().isoformat())
    appt_time = context.user_data.pop("appt_time", None)
    context.user_data["awaiting"] = None

    with db() as conn:
        conn.execute(
            "INSERT INTO appointments (chat_id, title, event_date, event_time, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, title, appt_date, appt_time, notes),
        )

    time_str = f" at {appt_time}" if appt_time else ""
    notes_str = f"\n📒 {notes}" if notes else ""
    event_d = date.fromisoformat(appt_date)
    confirm_text = (
        f"✅ Appointment saved!\n\n"
        f"📅 {title}\n"
        f"Date: {appt_date}{time_str} — {friendly_date(event_d)}"
        f"{notes_str}"
    )

    from keyboards import appts_list_kb
    appts = _get_appointments(chat_id)
    kb = appts_list_kb(appts)

    if query:
        await query.edit_message_text(confirm_text, reply_markup=kb)
    else:
        await update.message.reply_text(confirm_text, reply_markup=kb)


# ═══════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════

def _get_appointments(chat_id, include_done=True, limit=30) -> list[dict]:
    """Get all appointments for a user, sorted by date."""
    with db() as conn:
        if include_done:
            rows = conn.execute(
                "SELECT * FROM appointments WHERE chat_id = ? ORDER BY event_date ASC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM appointments WHERE chat_id = ? AND done = 0 ORDER BY event_date ASC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def get_appointments_for_date(chat_id: int, d: date) -> list[dict]:
    """Get appointments for a specific date (used by week_view and today)."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND event_date = ? ORDER BY event_time ASC",
            (chat_id, d.isoformat()),
        ).fetchall()
    return [dict(r) for r in rows]


def get_upcoming_appointments(chat_id: int, days_ahead: int = 7) -> list[dict]:
    """Get upcoming appointments within N days (used by today and scheduler)."""
    d = today()
    end = d + timedelta(days=days_ahead)
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND done = 0 "
            "AND event_date >= ? AND event_date <= ? ORDER BY event_date ASC, event_time ASC",
            (chat_id, d.isoformat(), end.isoformat()),
        ).fetchall()
    return [dict(r) for r in rows]


def _parse_date_loosely(text: str) -> str:
    """Best-effort date parsing. Returns ISO date string."""
    text = text.strip()

    # Try ISO format first
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d")
    except ValueError:
        pass

    # Try "Month Day" or "Month Day, Year"
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    text_lower = text.lower()
    for mname, mnum in months.items():
        if mname in text_lower:
            year_match = re.search(r"20\d{2}", text)
            year = int(year_match.group()) if year_match else datetime.now().year
            day_match = re.search(r"\b(\d{1,2})\b", text.replace(str(year), ""))
            day = int(day_match.group()) if day_match else 1
            try:
                return datetime(year, mnum, day).strftime("%Y-%m-%d")
            except ValueError:
                return datetime(year, mnum, 1).strftime("%Y-%m-%d")

    # Try MM/DD or MM-DD
    slash = re.match(r"(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?", text)
    if slash:
        m, d = int(slash.group(1)), int(slash.group(2))
        y = int(slash.group(3)) if slash.group(3) else datetime.now().year
        if y < 100:
            y += 2000
        try:
            return datetime(y, m, d).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return text


def _parse_time_loosely(text: str) -> str | None:
    """Best-effort time parsing. Returns HH:MM or None."""
    text = text.strip().lower()

    # Try HH:MM format
    match = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)?", text)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        ampm = match.group(3)
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"

    # Try "2pm", "2 pm", "14"
    match = re.match(r"(\d{1,2})\s*(am|pm)?", text)
    if match:
        h = int(match.group(1))
        ampm = match.group(2)
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        elif not ampm and h < 8:
            # Assume PM for small numbers without am/pm (nocturnal user)
            h += 12
        return f"{h:02d}:00"

    return None
