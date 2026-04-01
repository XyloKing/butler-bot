"""
📅 Universal button-based date picker handler.
Routes datepick:* callbacks for the field editor and other flows.

Flow: User taps a date-type edit button → field_editor launches date picker
→ user picks month → day → date is saved to DB.
"""
from datetime import date
from telegram import Update
from telegram.ext import ContextTypes

from database import db
from keyboards import (
    date_pick_month_kb, date_pick_day_kb,
)


async def datepick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle datepick:* callbacks for universal date picking.

    Callback data format: datepick:{module}:{item_id}:{field}:{action}:{value}
    Example: datepick:appts:3:event_date:month:4:2026
    """
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    parts = data.split(":")
    # datepick:{module}:{item_id}:{field}:{action}:{extra...}
    module = parts[1] if len(parts) > 1 else ""
    item_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    field = parts[3] if len(parts) > 3 else ""
    action = parts[4] if len(parts) > 4 else ""
    prefix = f"datepick:{module}:{item_id}:{field}"

    if action == "cancel":
        # Return to detail view
        await _return_to_detail(query, context, module, item_id, chat_id)

    elif action == "yr":
        # Year changed — show months for that year
        year = int(parts[5]) if len(parts) > 5 else date.today().year
        await query.edit_message_text(
            f"📅 Pick a month:",
            reply_markup=date_pick_month_kb(prefix, year),
        )

    elif action == "month":
        # Month selected — show day grid
        month = int(parts[5]) if len(parts) > 5 else 1
        year = int(parts[6]) if len(parts) > 6 else date.today().year
        await query.edit_message_text(
            "📅 Pick the day:",
            reply_markup=date_pick_day_kb(prefix, month, year),
        )

    elif action == "day":
        # Day selected — save to DB
        date_str = parts[5] if len(parts) > 5 else ""
        if not date_str:
            await query.edit_message_text("Something went wrong. Try again from the menu.")
            return

        # Map module to table
        from modules.field_editor import TABLE_MAP
        table = TABLE_MAP.get(module)
        if not table:
            await query.edit_message_text("Something went wrong. Try again from the menu.")
            return

        with db() as conn:
            conn.execute(
                f"UPDATE {table} SET {field} = ? WHERE id = ? AND chat_id = ?",
                (date_str, item_id, chat_id),
            )

        await query.edit_message_text(f"✅ Updated {field} → {date_str}")
        await _return_to_detail(query, context, module, item_id, chat_id, send_new=True)


async def _return_to_detail(query, context, module, item_id, chat_id, send_new=False):
    """Return to the appropriate detail view after date pick."""
    if module == "appts":
        from keyboards import appt_detail_kb
        with db() as conn:
            appt = conn.execute("SELECT * FROM appointments WHERE id = ?", (item_id,)).fetchone()
        if appt:
            from helpers import friendly_date as _fd, urgency_emoji as _ue, days_until as _du
            from modules.appointments import CATEGORIES, PRIORITY_LABELS, CATEGORY_EMOJI
            event_d = date.fromisoformat(appt["event_date"])
            delta = _du(event_d)
            urg = _ue(delta)
            time_str = f"\nTime: {appt['event_time']}" if appt["event_time"] else ""
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
            text = (
                f"📅 {appt['title']}\n"
                f"Category: {cat_label}\n"
                f"Date: {urg} {appt['event_date']} — {_fd(event_d)}"
                f"{time_str}\n"
                f"Priority: {prio_label}"
            )
            if send_new:
                await query.message.reply_text(text, reply_markup=appt_detail_kb(item_id, appt["done"]))
            else:
                await query.edit_message_text(text, reply_markup=appt_detail_kb(item_id, appt["done"]))

    elif module == "car":
        from keyboards import car_detail_kb
        with db() as conn:
            event = conn.execute("SELECT * FROM car_events WHERE id = ?", (item_id,)).fetchone()
        if event:
            text = f"🚗 {event['description']}\nDue: {event['due_date']}"
            if send_new:
                await query.message.reply_text(text, reply_markup=car_detail_kb(item_id, event["done"]))
            else:
                await query.edit_message_text(text, reply_markup=car_detail_kb(item_id, event["done"]))

    elif module == "creds":
        from keyboards import cred_detail_kb
        with db() as conn:
            cred = conn.execute("SELECT * FROM credentials WHERE id = ?", (item_id,)).fetchone()
        if cred:
            text = f"🎓 {cred['name']}\nExpires: {cred['expiry_date']}"
            if send_new:
                await query.message.reply_text(text, reply_markup=cred_detail_kb(item_id))
            else:
                await query.edit_message_text(text, reply_markup=cred_detail_kb(item_id))

    elif module == "meds":
        from keyboards import med_detail_kb
        with db() as conn:
            med = conn.execute("SELECT * FROM medications WHERE id = ?", (item_id,)).fetchone()
        if med:
            text = f"💊 {med['name']} {med['dosage'] or ''}"
            if send_new:
                await query.message.reply_text(text, reply_markup=med_detail_kb(item_id, med["taken_today"]))
            else:
                await query.edit_message_text(text, reply_markup=med_detail_kb(item_id, med["taken_today"]))

    elif module == "bills":
        from keyboards import bill_detail_kb
        with db() as conn:
            bill = conn.execute("SELECT * FROM bills WHERE id = ?", (item_id,)).fetchone()
        if bill:
            from helpers import format_money
            paid = "✅ PAID" if bill["paid_this_cycle"] else "⬜ UNPAID"
            text = f"💸 {bill['name']}\nAmount: {format_money(bill['amount'])}\nStatus: {paid}"
            if send_new:
                await query.message.reply_text(text, reply_markup=bill_detail_kb(item_id, bill["paid_this_cycle"]))
            else:
                await query.edit_message_text(text, reply_markup=bill_detail_kb(item_id, bill["paid_this_cycle"]))
    else:
        # Generic fallback
        from keyboards import back_to_menu_kb
        if send_new:
            await query.message.reply_text("Done.", reply_markup=back_to_menu_kb())
        else:
            await query.edit_message_text("Done.", reply_markup=back_to_menu_kb())
