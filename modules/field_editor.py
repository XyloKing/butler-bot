# Butler Bot
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
Universal inline field editor.
Any module can use this to edit any field on any table via buttons.
Stores pending edit info in context.user_data and handles the text response.
"""
from telegram import Update
from telegram.ext import ContextTypes
from database import db

# Human-readable prompts per field name
FIELD_PROMPTS = {
    # Bills
    "name": "New name?",
    "amount": "New amount? (number, or 'skip' to clear)",
    "due_day": "Due day of month? (1-31, or 'skip' to clear)",
    "frequency": "Frequency? (monthly / biweekly / weekly / once)",
    "account_user": "Account username or number?",
    # Car
    "description": "New description?",
    "due_date": "New due date? (YYYY-MM-DD or 'May 2026')",
    "mileage": "Current mileage?",
    # Credentials
    "credential_num": "License / credential number?",
    "state": "State? (e.g. PA, NJ)",
    "expiry_date": "Expiry date? (YYYY-MM-DD or 'June 2027')",
    "ceu_required": "How many CEUs required?",
    "ceu_completed": "How many CEUs completed so far?",
    "issuing_body": "Issuing organization?",
    "renewal_url": "Renewal website URL?",
    # Partners
    "emoji": "Pick an emoji for them (just send one emoji):",
    "target_dates_per_month": "Target dates per month? (number)",
    # Meds
    "dosage": "Dosage? (e.g. '20mg', or 'skip' to clear)",
    "refill_date": "Next refill date? (YYYY-MM-DD or 'skip')",
    # Notes
    "content": "New content?",
    # Appointments
    "title": "New title?",
    "event_date": "New date? (YYYY-MM-DD or 'March 29')",
    "event_time": "New time? (e.g. '2pm', '14:00', or 'skip' to clear)",
    "notes": "Notes? (or 'skip' to clear)",
}

# Fields that need numeric parsing
NUMERIC_FIELDS = {"amount", "due_day", "mileage", "ceu_required", "ceu_completed", "target_dates_per_month"}
# Fields that need time parsing
TIME_FIELDS = {"event_time"}
# Fields that need date parsing
DATE_FIELDS = {"due_date", "expiry_date", "refill_date", "event_date"}
# Fields where 'skip' means set to NULL
NULLABLE_FIELDS = {"amount", "due_day", "mileage", "dosage", "refill_date", "account_user",
                   "credential_num", "state", "issuing_body", "renewal_url", "event_time", "notes"}

# Table mapping for each module prefix
TABLE_MAP = {
    "bills": "bills",
    "car": "car_events",
    "creds": "credentials",
    "partners": "partners",
    "meds": "medications",
    "notes": "notes",
    "appts": "appointments",
}


async def start_field_edit(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           module: str, item_id: int, field: str):
    """Begin a field edit — send prompt and store state.
    For date fields, launch the button-based date picker instead of text input.
    """
    query = update.callback_query

    # Date fields get the button-based picker
    if field in DATE_FIELDS:
        from keyboards import date_pick_month_kb
        prefix = f"datepick:{module}:{item_id}:{field}"
        await query.edit_message_text(
            "📅 Pick a date — choose a month:",
            reply_markup=date_pick_month_kb(prefix),
        )
        return

    # Medication frequency gets button picker
    if field == "frequency" and module == "meds":
        from keyboards import frequency_picker_kb
        await query.edit_message_text(
            "How often do you take this medication?",
            reply_markup=frequency_picker_kb(module, item_id),
        )
        return

    # Bill frequency gets button picker
    if field == "frequency" and module == "bills":
        from keyboards import bill_frequency_picker_kb
        await query.edit_message_text(
            "How often is this bill?",
            reply_markup=bill_frequency_picker_kb(item_id),
        )
        return

    # Target dates per month gets button picker
    if field == "target_dates_per_month" and module == "partners":
        from keyboards import target_dates_picker_kb
        await query.edit_message_text(
            "How many dates per month is your target?",
            reply_markup=target_dates_picker_kb(item_id),
        )
        return

    prompt = FIELD_PROMPTS.get(field, f"New value for {field}?")
    context.user_data["awaiting"] = "field_edit"
    context.user_data["field_edit_module"] = module
    context.user_data["field_edit_id"] = item_id
    context.user_data["field_edit_field"] = field
    await query.edit_message_text(prompt)


async def handle_field_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text response for a pending field edit. Returns True if consumed."""
    if context.user_data.get("awaiting") != "field_edit":
        return False

    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    module = context.user_data.pop("field_edit_module")
    item_id = context.user_data.pop("field_edit_id")
    field = context.user_data.pop("field_edit_field")
    context.user_data["awaiting"] = None

    table = TABLE_MAP.get(module)
    if not table:
        await update.message.reply_text("Something went wrong. Try again from the menu.")
        return True

    # Parse value
    value = text
    if text.lower() in ("skip", "clear", "none") and field in NULLABLE_FIELDS:
        value = None
    elif field in NUMERIC_FIELDS:
        try:
            cleaned = text.replace("$", "").replace(",", "")
            value = int(cleaned) if field != "amount" else float(cleaned)
        except ValueError:
            await update.message.reply_text(f"Need a number for {field}. Try again from the item.")
            return True
    elif field in TIME_FIELDS:
        from modules.appointments import _parse_time_loosely
        value = _parse_time_loosely(text)
    elif field in DATE_FIELDS:
        from modules.onboarding import _parse_date_loosely
        value = _parse_date_loosely(text)

    # Update DB
    with db() as conn:
        conn.execute(
            f"UPDATE {table} SET {field} = ? WHERE id = ? AND chat_id = ?",
            (value, item_id, chat_id),
        )

    # Send confirmation and return to detail view
    display = value if value is not None else "(cleared)"
    await update.message.reply_text(f"✅ Updated {field} → {display}")

    # Send the detail view back
    await _send_detail_view(update, context, module, item_id, chat_id)
    return True


async def _send_detail_view(update, context, module, item_id, chat_id):
    """Re-show the detail view after an edit."""
    if module == "bills":
        from modules.bills import _get_bills
        from keyboards import bill_detail_kb
        with db() as conn:
            bill = conn.execute("SELECT * FROM bills WHERE id = ?", (item_id,)).fetchone()
        if bill:
            from helpers import format_money
            paid = "✅ PAID" if bill["paid_this_cycle"] else "⬜ UNPAID"
            text = (
                f"💸 {bill['name']}\n"
                f"Amount: {format_money(bill['amount'])}\n"
                f"Status: {paid}\n"
                f"Frequency: {bill['frequency'] or 'monthly'}\n"
            )
            if bill["due_day"]:
                text += f"Due: day {bill['due_day']}\n"
            if bill["account_user"]:
                text += f"Account: {bill['account_user']}\n"
            await update.message.reply_text(text, reply_markup=bill_detail_kb(item_id, bill["paid_this_cycle"]))

    elif module == "car":
        from keyboards import car_detail_kb
        with db() as conn:
            event = conn.execute("SELECT * FROM car_events WHERE id = ?", (item_id,)).fetchone()
        if event:
            await update.message.reply_text(
                f"🚗 {event['description']}\nDue: {event['due_date']}",
                reply_markup=car_detail_kb(item_id, event["done"]),
            )

    elif module == "creds":
        from keyboards import cred_detail_kb
        with db() as conn:
            cred = conn.execute("SELECT * FROM credentials WHERE id = ?", (item_id,)).fetchone()
        if cred:
            await update.message.reply_text(
                f"🎓 {cred['name']}\nExpires: {cred['expiry_date']}",
                reply_markup=cred_detail_kb(item_id),
            )

    elif module == "partners":
        from keyboards import partner_detail_kb
        with db() as conn:
            partner = conn.execute("SELECT * FROM partners WHERE id = ?", (item_id,)).fetchone()
        if partner:
            await update.message.reply_text(
                f"{partner['emoji'] or '💜'} {partner['name']}",
                reply_markup=partner_detail_kb(item_id),
            )

    elif module == "meds":
        from keyboards import med_detail_kb
        with db() as conn:
            med = conn.execute("SELECT * FROM medications WHERE id = ?", (item_id,)).fetchone()
        if med:
            await update.message.reply_text(
                f"💊 {med['name']} {med['dosage'] or ''}",
                reply_markup=med_detail_kb(item_id, med["taken_today"]),
            )

    elif module == "appts":
        from keyboards import appt_detail_kb
        with db() as conn:
            appt = conn.execute("SELECT * FROM appointments WHERE id = ?", (item_id,)).fetchone()
        if appt:
            from helpers import friendly_date as _fd, urgency_emoji as _ue, days_until as _du
            from datetime import date as _date
            from modules.appointments import CATEGORIES, PRIORITY_LABELS
            event_d = _date.fromisoformat(appt["event_date"])
            delta = _du(event_d)
            urg = _ue(delta)
            time_str = f"\nTime: {appt['event_time']}" if appt["event_time"] else ""
            cat = appt.get("category") or "other"
            try:
                priority = appt["priority"] if appt["priority"] is not None else 2
            except (IndexError, KeyError):
                priority = 2
            cat_label = CATEGORIES.get(cat, cat)
            prio_label = PRIORITY_LABELS.get(priority, str(priority))
            text = (
                f"📅 {appt['title']}\n"
                f"Category: {cat_label}\n"
                f"Date: {urg} {appt['event_date']} — {_fd(event_d)}"
                f"{time_str}\n"
                f"Priority: {prio_label}"
            )
            await update.message.reply_text(
                text,
                reply_markup=appt_detail_kb(item_id, appt["done"]),
            )
