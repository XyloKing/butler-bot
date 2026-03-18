"""
📅 Appointments / Events module.
Add, view, edit, delete appointments with date parsing.
Shows on week view + today view + scheduler reminders.

New flow: Title → Category → Date → Time → Notes → Priority/Reminder → Save
"""
import re
from datetime import datetime, date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import db
from helpers import today, days_until, friendly_date, urgency_emoji
from keyboards import back_to_menu_kb

AWAITING_APPT_TITLE = "appt_title"
AWAITING_APPT_DATE = "appt_date"
AWAITING_APPT_TIME = "appt_time"
AWAITING_APPT_NOTES = "appt_notes"

# Category definitions
CATEGORIES = {
    "medical":    "🏥 Medical",
    "car_admin":  "🚗 Car / Admin",
    "credential": "🎓 Credential",
    "financial":  "💰 Financial",
    "social":     "🎂 Social",
    "other":      "📋 Other",
}

CATEGORY_EMOJI = {
    "medical": "🏥",
    "car_admin": "🚗",
    "credential": "🎓",
    "financial": "💰",
    "social": "🎂",
    "other": "📋",
}

# Smart priority defaults per category
CATEGORY_DEFAULT_PRIORITY = {
    "medical": 3,
    "car_admin": 2,
    "credential": 4,
    "financial": 4,
    "social": 1,
    "other": 2,
}

# Priority labels
PRIORITY_LABELS = {
    0: "🔕 None",
    1: "🔔 Low",
    2: "🔔🔔 Moderate",
    3: "🔔🔔🔔 High",
    4: "🚨 Critical",
}

# Reminder schedule per priority level (days before event)
PRIORITY_REMINDERS = {
    0: [],
    1: [1],
    2: [1, 0],
    3: [3, 1, 0],       # + follow-up
    4: [7, 3, 1, 0],    # + follow-up
}


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
        # User chose to skip adding notes — now go to priority picker
        await _show_priority_picker(update, context, notes=None)

    # ── Category picker (during creation) ──────────────
    elif action == "category":
        cat = parts[2] if len(parts) > 2 else "other"
        context.user_data["appt_category"] = cat
        context.user_data["awaiting"] = AWAITING_APPT_DATE
        cat_label = CATEGORIES.get(cat, cat)
        title = context.user_data.get("appt_title", "")
        await query.edit_message_text(
            f"📅 {title}\n"
            f"Category: {cat_label}\n\n"
            "When is it?\n"
            "(e.g. 'March 29', '2026-04-15', 'April 3 2026')"
        )

    # ── Priority picker (during creation) ──────────────
    elif action == "priority_ok":
        await _save_with_priority(update, context)

    elif action == "priority_none":
        context.user_data["appt_priority"] = 0
        context.user_data["appt_reminder_level"] = "none"
        await _save_with_priority(update, context)

    elif action == "priority_up":
        current = context.user_data.get("appt_priority", 2)
        new_p = min(current + 1, 4)
        context.user_data["appt_priority"] = new_p
        await _show_priority_picker_update(query, context)

    elif action == "priority_down":
        current = context.user_data.get("appt_priority", 2)
        new_p = max(current - 1, 0)
        context.user_data["appt_priority"] = new_p
        if new_p == 0:
            context.user_data["appt_reminder_level"] = "none"
        await _show_priority_picker_update(query, context)

    # ── Edit category (from detail view) ───────────────
    elif action == "editcategory":
        appt_id = int(parts[2])
        await _show_edit_category_picker(query, appt_id)

    elif action == "setcategory":
        appt_id = int(parts[2])
        cat = parts[3]
        with db() as conn:
            conn.execute(
                "UPDATE appointments SET category = ? WHERE id = ? AND chat_id = ?",
                (cat, appt_id, chat_id),
            )
        await query.edit_message_text(f"✅ Category → {CATEGORIES.get(cat, cat)}")
        await _show_appt_detail_new(query, chat_id, appt_id)

    # ── Edit priority (from detail view) ───────────────
    elif action == "editpriority":
        appt_id = int(parts[2])
        await _show_edit_priority_picker(query, appt_id)

    elif action == "setpriority":
        appt_id = int(parts[2])
        prio = int(parts[3])
        reminder_level = "none" if prio == 0 else "smart"
        with db() as conn:
            conn.execute(
                "UPDATE appointments SET priority = ?, reminder_level = ? "
                "WHERE id = ? AND chat_id = ?",
                (prio, reminder_level, appt_id, chat_id),
            )
        await query.edit_message_text(f"✅ Priority → {PRIORITY_LABELS.get(prio, str(prio))}")
        await _show_appt_detail_new(query, chat_id, appt_id)

    # ── Reminder action buttons ─────────────────────────
    elif action == "remind_done":
        appt_id = int(parts[2])
        with db() as conn:
            conn.execute(
                "UPDATE appointments SET done = 1 WHERE id = ? AND chat_id = ?",
                (appt_id, chat_id),
            )
        await query.edit_message_text("✅ Marked done!")

    elif action == "remind_later":
        # Just dismiss — the next hourly check will re-send if appropriate
        await query.edit_message_text("⏰ Got it, I'll remind you later.")

    elif action == "remind_view":
        appt_id = int(parts[2])
        await _show_appt_detail_new(query, chat_id, appt_id)

    elif action == "snooze2h":
        # Log a "snooze" so the hourly check skips for ~2 hours
        appt_id = int(parts[2])
        with db() as conn:
            conn.execute(
                "INSERT INTO reminder_log (chat_id, category, ref_id) VALUES (?, ?, ?)",
                (chat_id, "appt_snooze", appt_id),
            )
        await query.edit_message_text("⏰ Snoozed for a couple hours.")


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

    # Get new fields safely
    try:
        cat = appt["category"] or "other"
    except (IndexError, KeyError):
        cat = "other"
    try:
        priority = appt["priority"] if appt["priority"] is not None else 2
    except (IndexError, KeyError):
        priority = 2

    cat_label = CATEGORIES.get(cat, cat)
    prio_label = PRIORITY_LABELS.get(priority, str(priority))

    lines = [
        f"📅 {appt['title']}",
        f"Category: {cat_label}",
        f"Date: {urg} {appt['event_date']} — {friendly_date(event_date)}",
    ]
    if appt["event_time"]:
        lines.append(f"Time: {appt['event_time']}")
    lines.append(f"Priority: {prio_label}")
    lines.append(f"Status: {done_str}")
    if appt["notes"]:
        lines.append(f"\n📒 {appt['notes']}")

    text = "\n".join(lines)
    await query.edit_message_text(text, reply_markup=appt_detail_kb(appt_id, appt["done"]))


async def _show_appt_detail_new(query, chat_id, appt_id):
    """Re-show detail after an edit (sends as new message)."""
    with db() as conn:
        appt = conn.execute(
            "SELECT * FROM appointments WHERE id = ? AND chat_id = ?",
            (appt_id, chat_id)
        ).fetchone()

    if not appt:
        return

    from keyboards import appt_detail_kb

    done_str = "✅ Done" if appt["done"] else "⬜ Pending"
    event_date = date.fromisoformat(appt["event_date"])
    delta = days_until(event_date)
    urg = urgency_emoji(delta)

    try:
        cat = appt["category"] or "other"
    except (IndexError, KeyError):
        cat = "other"
    try:
        priority = appt["priority"] if appt["priority"] is not None else 2
    except (IndexError, KeyError):
        priority = 2

    cat_label = CATEGORIES.get(cat, cat)
    prio_label = PRIORITY_LABELS.get(priority, str(priority))

    lines = [
        f"📅 {appt['title']}",
        f"Category: {cat_label}",
        f"Date: {urg} {appt['event_date']} — {friendly_date(event_date)}",
    ]
    if appt["event_time"]:
        lines.append(f"Time: {appt['event_time']}")
    lines.append(f"Priority: {prio_label}")
    lines.append(f"Status: {done_str}")
    if appt["notes"]:
        lines.append(f"\n📒 {appt['notes']}")

    text = "\n".join(lines)
    await query.message.reply_text(text, reply_markup=appt_detail_kb(appt_id, appt["done"]))


# ═══════════════════════════════════════════════════════
# ADD FLOW — title → category → date → time → notes → priority → save
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
    """Step 1: Got the title, show category picker."""
    text = update.message.text.strip()
    context.user_data["appt_title"] = text
    context.user_data["awaiting"] = None  # Waiting for button press, not text

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏥 Medical", callback_data="appts:category:medical"),
            InlineKeyboardButton("🚗 Car / Admin", callback_data="appts:category:car_admin"),
        ],
        [
            InlineKeyboardButton("🎓 Credential", callback_data="appts:category:credential"),
            InlineKeyboardButton("💰 Financial", callback_data="appts:category:financial"),
        ],
        [
            InlineKeyboardButton("🎂 Social", callback_data="appts:category:social"),
            InlineKeyboardButton("📋 Other", callback_data="appts:category:other"),
        ],
    ])
    await update.message.reply_text(
        f"📅 Got it: \"{text}\"\n\n"
        "What category?",
        reply_markup=kb,
    )
    return True


async def _handle_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Step 3: Got the date, now ask for time (optional)."""
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
    """Step 4: Got the time (or skip), now ask for notes (optional)."""
    text = update.message.text.strip()
    parsed_time = _parse_time_loosely(text)
    await _save_appointment(update, context, event_time=parsed_time)
    return True


async def _save_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE, event_time=None):
    """After date+time collected, ask for notes."""
    context.user_data["appt_time"] = event_time
    context.user_data["awaiting"] = AWAITING_APPT_NOTES

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
    """Step 5: Got notes, go to priority picker."""
    text = update.message.text.strip()
    await _show_priority_picker(update, context, notes=text)
    return True


async def _show_priority_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, notes=None):
    """Show the priority/reminder picker before saving."""
    context.user_data["appt_notes"] = notes
    context.user_data["awaiting"] = None  # Waiting for button press

    cat = context.user_data.get("appt_category", "other")
    default_priority = CATEGORY_DEFAULT_PRIORITY.get(cat, 2)
    context.user_data["appt_priority"] = default_priority
    context.user_data["appt_reminder_level"] = "smart" if default_priority > 0 else "none"

    query = update.callback_query
    text = _build_priority_text(context)
    kb = _build_priority_kb()

    if query:
        await query.edit_message_text(text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)


async def _show_priority_picker_update(query, context):
    """Update the priority picker after up/down button."""
    text = _build_priority_text(context)
    kb = _build_priority_kb()
    await query.edit_message_text(text, reply_markup=kb)


def _build_priority_text(context) -> str:
    """Build the priority picker message text."""
    title = context.user_data.get("appt_title", "")
    appt_date = context.user_data.get("appt_date", "")
    cat = context.user_data.get("appt_category", "other")
    priority = context.user_data.get("appt_priority", 2)

    cat_label = CATEGORIES.get(cat, cat)
    prio_label = PRIORITY_LABELS.get(priority, str(priority))
    reminders = PRIORITY_REMINDERS.get(priority, [])

    lines = [
        f"📅 {title}",
        f"Date: {appt_date}",
        f"Category: {cat_label}",
        "",
        f"Suggested reminders: {prio_label}",
    ]

    if reminders:
        for d in reminders:
            if d == 0:
                lines.append("  • Morning of")
            elif d == 1:
                lines.append("  • Day before")
            elif d == 3:
                lines.append("  • 3 days before")
            elif d == 7:
                lines.append("  • 1 week before")
        if priority >= 3:
            lines.append("  • Follow-up if not done")
    else:
        lines.append("  No reminders — just shows on calendar.")

    return "\n".join(lines)


def _build_priority_kb() -> InlineKeyboardMarkup:
    """Build the priority picker keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Looks good", callback_data="appts:priority_ok"),
            InlineKeyboardButton("🔕 No reminders", callback_data="appts:priority_none"),
        ],
        [
            InlineKeyboardButton("⬆️ More urgent", callback_data="appts:priority_up"),
            InlineKeyboardButton("⬇️ Less urgent", callback_data="appts:priority_down"),
        ],
    ])


async def _save_with_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the appointment with all collected data including priority."""
    query = update.callback_query
    chat_id = query.message.chat_id if query else update.effective_chat.id

    title = context.user_data.pop("appt_title", "Untitled")
    appt_date = context.user_data.pop("appt_date", today().isoformat())
    appt_time = context.user_data.pop("appt_time", None)
    notes = context.user_data.pop("appt_notes", None)
    category = context.user_data.pop("appt_category", "other")
    priority = context.user_data.pop("appt_priority", 2)
    reminder_level = context.user_data.pop("appt_reminder_level", "smart")
    # Fully clear awaiting — use pop, not assignment, so no stale None lingers
    context.user_data.pop("awaiting", None)

    with db() as conn:
        conn.execute(
            "INSERT INTO appointments "
            "(chat_id, title, event_date, event_time, notes, category, priority, reminder_level) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, title, appt_date, appt_time, notes, category, priority, reminder_level),
        )

    time_str = f" at {appt_time}" if appt_time else ""
    notes_str = f"\n📒 {notes}" if notes else ""
    cat_emoji = CATEGORY_EMOJI.get(category, "📋")
    prio_label = PRIORITY_LABELS.get(priority, "")
    event_d = date.fromisoformat(appt_date)
    confirm_text = (
        f"✅ Appointment saved!\n\n"
        f"📅 {title}\n"
        f"Category: {cat_emoji} {category.replace('_', ' ').title()}\n"
        f"Date: {appt_date}{time_str} — {friendly_date(event_d)}\n"
        f"Priority: {prio_label}"
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
# EDIT PICKERS (category & priority — button-based, not text)
# ═══════════════════════════════════════════════════════

async def _show_edit_category_picker(query, appt_id):
    """Show category picker for editing an existing appointment."""
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏥 Medical", callback_data=f"appts:setcategory:{appt_id}:medical"),
            InlineKeyboardButton("🚗 Car/Admin", callback_data=f"appts:setcategory:{appt_id}:car_admin"),
        ],
        [
            InlineKeyboardButton("🎓 Credential", callback_data=f"appts:setcategory:{appt_id}:credential"),
            InlineKeyboardButton("💰 Financial", callback_data=f"appts:setcategory:{appt_id}:financial"),
        ],
        [
            InlineKeyboardButton("🎂 Social", callback_data=f"appts:setcategory:{appt_id}:social"),
            InlineKeyboardButton("📋 Other", callback_data=f"appts:setcategory:{appt_id}:other"),
        ],
        [InlineKeyboardButton("⬅️ Cancel", callback_data=f"appts:detail:{appt_id}")],
    ])
    await query.edit_message_text("📂 Pick a new category:", reply_markup=kb)


async def _show_edit_priority_picker(query, appt_id):
    """Show priority picker for editing an existing appointment."""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔕 None", callback_data=f"appts:setpriority:{appt_id}:0")],
        [InlineKeyboardButton("🔔 Low", callback_data=f"appts:setpriority:{appt_id}:1")],
        [InlineKeyboardButton("🔔🔔 Moderate", callback_data=f"appts:setpriority:{appt_id}:2")],
        [InlineKeyboardButton("🔔🔔🔔 High", callback_data=f"appts:setpriority:{appt_id}:3")],
        [InlineKeyboardButton("🚨 Critical", callback_data=f"appts:setpriority:{appt_id}:4")],
        [InlineKeyboardButton("⬅️ Cancel", callback_data=f"appts:detail:{appt_id}")],
    ])
    await query.edit_message_text("⚡ Pick priority level:", reply_markup=kb)


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

    # Strip ordinal suffixes (1st, 2nd, 3rd, 4th, 29th, etc.)
    text = re.sub(r'(\d+)(st|nd|rd|th)\b', r'\1', text, flags=re.IGNORECASE)

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
