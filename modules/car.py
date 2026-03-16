"""
🚗 Car / Admin module.
Low-maintenance tracking with countdown alerts.
"""
from datetime import date
from telegram import Update
from telegram.ext import ContextTypes

from database import db
from helpers import today, days_until, friendly_date, urgency_emoji
from keyboards import car_list_kb, car_detail_kb, back_to_menu_kb, confirm_delete_kb

AWAITING_CAR_DESC = "car_desc"
AWAITING_CAR_DATE = "car_date"
AWAITING_CAR_TYPE = "car_type"


async def car_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all car:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    item_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

    if action == "view":
        await _show_car_list(query, chat_id)

    elif action == "detail":
        await _show_car_detail(query, chat_id, item_id)

    elif action == "done":
        with db() as conn:
            conn.execute("UPDATE car_events SET done = 1 WHERE id = ? AND chat_id = ?",
                         (item_id, chat_id))
            event = conn.execute("SELECT description FROM car_events WHERE id = ?", (item_id,)).fetchone()
        desc = event["description"] if event else "Item"
        await query.edit_message_text(f"✅ {desc} — done.", reply_markup=back_to_menu_kb())

    elif action == "undone":
        with db() as conn:
            conn.execute("UPDATE car_events SET done = 0 WHERE id = ? AND chat_id = ?",
                         (item_id, chat_id))
        await _show_car_detail(query, chat_id, item_id)

    elif action == "add":
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        await query.edit_message_text(
            "What type of item?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛢 Oil Change",    callback_data="car:addtype:oil_change")],
                [InlineKeyboardButton("🔍 Inspection",    callback_data="car:addtype:inspection")],
                [InlineKeyboardButton("📋 Registration",  callback_data="car:addtype:registration")],
                [InlineKeyboardButton("🔧 Tire / Brake",  callback_data="car:addtype:tire_brake")],
                [InlineKeyboardButton("✏️ Custom",        callback_data="car:addtype:custom")],
                [InlineKeyboardButton("⬅️ Back",          callback_data="car:view")],
            ]),
        )

    elif action == "addtype":
        event_type = parts[2] if len(parts) > 2 else "custom"
        context.user_data["new_car_type"] = event_type
        type_labels = {
            "oil_change": "Oil Change",
            "inspection": "State Inspection",
            "registration": "Registration Renewal",
            "tire_brake": "Tire / Brake Service",
            "custom": "Custom Item",
        }
        if event_type == "custom":
            context.user_data["awaiting"] = AWAITING_CAR_DESC
            await query.edit_message_text("Description?")
        else:
            context.user_data["new_car_desc"] = type_labels.get(event_type, event_type)
            context.user_data["awaiting"] = AWAITING_CAR_DATE
            await query.edit_message_text(
                f"When is the {type_labels.get(event_type, 'item')} due?\n"
                "(e.g. '2026-05-18' or 'May 2026')"
            )

    elif action == "editfield":
        field = parts[3] if len(parts) > 3 else "due_date"
        from modules.field_editor import start_field_edit
        await start_field_edit(update, context, "car", item_id, field)

    elif action == "delete":
        with db() as conn:
            event = conn.execute("SELECT description FROM car_events WHERE id = ? AND chat_id = ?",
                                 (item_id, chat_id)).fetchone()
        desc = event["description"] if event else "this item"
        await query.edit_message_text(f"Delete {desc}?", reply_markup=confirm_delete_kb("car", item_id))

    elif action == "confirm_delete":
        with db() as conn:
            conn.execute("DELETE FROM car_events WHERE id = ? AND chat_id = ?", (item_id, chat_id))
        await query.edit_message_text("Deleted.", reply_markup=back_to_menu_kb())


async def _show_car_list(query, chat_id):
    events = _get_car_events(chat_id)
    if not events:
        await query.edit_message_text(
            "🚗 No car/admin items yet.\n\nTap below to add one.",
            reply_markup=car_list_kb([]),
        )
        return

    text = "🚗 CAR / ADMIN\n\nTap an item for details:"
    await query.edit_message_text(text, reply_markup=car_list_kb(events))


async def _show_car_detail(query, chat_id, event_id):
    with db() as conn:
        event = conn.execute("SELECT * FROM car_events WHERE id = ? AND chat_id = ?",
                             (event_id, chat_id)).fetchone()
    if not event:
        await query.edit_message_text("Item not found.", reply_markup=back_to_menu_kb())
        return

    due = date.fromisoformat(event["due_date"])
    delta = days_until(due)
    urg = urgency_emoji(delta)

    lines = [
        f"🚗 {event['description']}",
        f"Type: {event['event_type']}",
        f"Due: {event['due_date']} — {friendly_date(due)}",
        f"Status: {'✅ Done' if event['done'] else f'{urg} Pending'}",
    ]
    if event["mileage"]:
        lines.append(f"Mileage: {event['mileage']:,}")
    if event["notes"]:
        lines.append(f"📒 {event['notes']}")

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=car_detail_kb(event_id, event["done"]),
    )


def _get_car_events(chat_id) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM car_events WHERE chat_id = ? ORDER BY done, due_date",
            (chat_id,)
        ).fetchall()
    return [dict(r) for r in rows]


async def handle_car_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for car operations."""
    awaiting = context.user_data.get("awaiting")
    if not awaiting or not awaiting.startswith("car"):
        return False

    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if awaiting == AWAITING_CAR_DESC:
        context.user_data["new_car_desc"] = text
        context.user_data["awaiting"] = AWAITING_CAR_DATE
        await update.message.reply_text("When is it due? (e.g. '2026-05-18' or 'May 2026')")
        return True

    if awaiting == AWAITING_CAR_DATE:
        from modules.onboarding import _parse_date_loosely
        due_date = _parse_date_loosely(text)

        # Check if this is an edit
        edit_id = context.user_data.pop("edit_car_id", None)
        if edit_id:
            with db() as conn:
                conn.execute("UPDATE car_events SET due_date = ? WHERE id = ? AND chat_id = ?",
                             (due_date, edit_id, chat_id))
            context.user_data["awaiting"] = None
            await update.message.reply_text(f"✅ Updated due date to {due_date}.",
                                            reply_markup=car_detail_kb(edit_id, False))
            return True

        desc = context.user_data.pop("new_car_desc", "Car item")
        event_type = context.user_data.pop("new_car_type", "custom")
        context.user_data["awaiting"] = None

        with db() as conn:
            conn.execute(
                "INSERT INTO car_events (chat_id, event_type, description, due_date) VALUES (?, ?, ?, ?)",
                (chat_id, event_type, desc, due_date),
            )

        events = _get_car_events(chat_id)
        await update.message.reply_text(
            f"✅ Added: {desc} — due {due_date}",
            reply_markup=car_list_kb(events),
        )
        return True

    return False
