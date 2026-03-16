"""
💸 Money & Bills module.
Payday-centered, aggressive nag-until-paid system.
"""
from datetime import date
from telegram import Update
from telegram.ext import ContextTypes

from database import db, get_user
from helpers import (
    today, days_until, friendly_date, urgency_emoji, format_money,
    is_payday, next_payday,
)
from keyboards import bills_list_kb, bill_detail_kb, back_to_menu_kb

# Text-input states
AWAITING_BILL_NAME = "bill_name"
AWAITING_BILL_AMOUNT = "bill_amount"
AWAITING_BILL_DUE = "bill_due_day"
AWAITING_BILL_EDIT_FIELD = "bill_edit_field"
AWAITING_BILL_EDIT_VALUE = "bill_edit_value"


async def bills_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all bills:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    item_id = int(parts[2]) if len(parts) > 2 else None

    if action == "view":
        await _show_bills_list(query, chat_id)

    elif action == "detail":
        await _show_bill_detail(query, chat_id, item_id)

    elif action == "paid":
        with db() as conn:
            conn.execute("UPDATE bills SET paid_this_cycle = 1 WHERE id = ? AND chat_id = ?",
                         (item_id, chat_id))
            bill = conn.execute("SELECT name FROM bills WHERE id = ?", (item_id,)).fetchone()
        name = bill["name"] if bill else "Bill"
        await query.edit_message_text(
            f"✅ {name} marked PAID. Nice.\n\nOne less thing to worry about.",
            reply_markup=bills_list_kb(await _get_bills(chat_id)),
        )

    elif action == "unpaid":
        with db() as conn:
            conn.execute("UPDATE bills SET paid_this_cycle = 0 WHERE id = ? AND chat_id = ?",
                         (item_id, chat_id))
        await _show_bills_list(query, chat_id)

    elif action == "add":
        await query.edit_message_text("What's the bill called? (e.g. 'Mortgage', 'PECO')")
        context.user_data["awaiting"] = AWAITING_BILL_NAME

    elif action == "payday":
        await _show_payday_summary(query, chat_id)

    elif action == "delete":
        from keyboards import confirm_delete_kb
        with db() as conn:
            bill = conn.execute("SELECT name FROM bills WHERE id = ? AND chat_id = ?",
                                (item_id, chat_id)).fetchone()
        name = bill["name"] if bill else "this bill"
        await query.edit_message_text(
            f"Delete {name}?",
            reply_markup=confirm_delete_kb("bills", item_id),
        )

    elif action == "confirm_delete":
        with db() as conn:
            conn.execute("DELETE FROM bills WHERE id = ? AND chat_id = ?", (item_id, chat_id))
        await query.edit_message_text("Deleted.", reply_markup=back_to_menu_kb())

    elif action == "editfield":
        field = parts[3] if len(parts) > 3 else "name"
        from modules.field_editor import start_field_edit
        await start_field_edit(update, context, "bills", item_id, field)


async def _show_bills_list(query, chat_id):
    bills = await _get_bills(chat_id)
    if not bills:
        await query.edit_message_text(
            "No bills yet.\n\nTap below to add one.",
            reply_markup=bills_list_kb([]),
        )
        return

    d = today()
    unpaid = [b for b in bills if not b["paid_this_cycle"]]
    paid = [b for b in bills if b["paid_this_cycle"]]
    total_unpaid = sum((b["amount"] or 0) for b in unpaid)

    payday_str = ""
    if is_payday(d):
        payday_str = "💰 IT'S PAYDAY\n"
    else:
        np = next_payday()
        payday_str = f"💰 Next payday: {friendly_date(np)}\n"

    text = (
        f"💸 MONEY & BILLS\n"
        f"{payday_str}\n"
        f"Unpaid: {len(unpaid)} bills — {format_money(total_unpaid)}\n"
        f"Paid this cycle: {len(paid)} ✅\n\n"
        f"Tap a bill for details:"
    )
    await query.edit_message_text(text, reply_markup=bills_list_kb(bills))


async def _show_bill_detail(query, chat_id, bill_id):
    with db() as conn:
        bill = conn.execute("SELECT * FROM bills WHERE id = ? AND chat_id = ?",
                            (bill_id, chat_id)).fetchone()
    if not bill:
        await query.edit_message_text("Bill not found.", reply_markup=back_to_menu_kb())
        return

    paid = "✅ PAID" if bill["paid_this_cycle"] else "⬜ UNPAID"
    text = (
        f"{'─' * 25}\n"
        f"💸 {bill['name']}\n"
        f"Amount: {format_money(bill['amount'])}\n"
        f"Status: {paid}\n"
        f"Frequency: {bill['frequency'] or 'monthly'}\n"
    )
    if bill["due_day"]:
        text += f"Due: day {bill['due_day']} of each month\n"
    if bill["account_user"]:
        text += f"Account: {bill['account_user']}\n"
    if bill["notes"]:
        text += f"📒 {bill['notes']}\n"

    await query.edit_message_text(text, reply_markup=bill_detail_kb(bill_id, bill["paid_this_cycle"]))


async def _show_payday_summary(query, chat_id):
    bills = await _get_bills(chat_id)
    unpaid = [b for b in bills if not b["paid_this_cycle"]]
    total = sum((b["amount"] or 0) for b in unpaid)

    lines = ["💰 PAYDAY BREAKDOWN\n"]
    for b in unpaid:
        lines.append(f"  ⬜ {b['name']: <20} {format_money(b['amount'])}")
    lines.append(f"\n  {'─' * 30}")
    lines.append(f"  TOTAL DUE:          {format_money(total)}")

    from keyboards import back_to_menu_kb
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Bills", callback_data="bills:view")],
    ])
    await query.edit_message_text("\n".join(lines), reply_markup=kb)


async def _get_bills(chat_id) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM bills WHERE chat_id = ? ORDER BY paid_this_cycle, name",
            (chat_id,)
        ).fetchall()
    return [dict(r) for r in rows]


async def handle_bill_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for bill creation/editing."""
    awaiting = context.user_data.get("awaiting")
    if not awaiting or not awaiting.startswith("bill"):
        return False

    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if awaiting == AWAITING_BILL_NAME:
        context.user_data["new_bill_name"] = text
        context.user_data["awaiting"] = AWAITING_BILL_AMOUNT
        await update.message.reply_text(f"How much is {text}? (Just the number, or 'skip')")
        return True

    if awaiting == AWAITING_BILL_AMOUNT:
        name = context.user_data.pop("new_bill_name", "Bill")
        amount = None
        if text.lower() != "skip":
            try:
                amount = float(text.replace("$", "").replace(",", ""))
            except ValueError:
                pass

        context.user_data["new_bill_amount"] = amount
        context.user_data["new_bill_name_final"] = name
        context.user_data["awaiting"] = AWAITING_BILL_DUE
        await update.message.reply_text("Due day of the month? (1-31, or 'skip')")
        return True

    if awaiting == AWAITING_BILL_DUE:
        name = context.user_data.pop("new_bill_name_final", "Bill")
        amount = context.user_data.pop("new_bill_amount", None)
        due_day = None
        if text.lower() != "skip":
            try:
                due_day = int(text)
            except ValueError:
                pass

        with db() as conn:
            conn.execute(
                "INSERT INTO bills (chat_id, name, amount, due_day) VALUES (?, ?, ?, ?)",
                (chat_id, name, amount, due_day),
            )
        context.user_data["awaiting"] = None

        amt_str = f" — {format_money(amount)}" if amount else ""
        bills = await _get_bills(chat_id)
        await update.message.reply_text(
            f"✅ Added: {name}{amt_str}\n\nTap a bill for details:",
            reply_markup=bills_list_kb(bills),
        )
        return True

    if awaiting == AWAITING_BILL_EDIT_VALUE:
        bill_id = context.user_data.pop("edit_bill_id", None)
        field = context.user_data.pop("edit_bill_field", "name")
        context.user_data["awaiting"] = None

        if field == "amount":
            try:
                text = float(text.replace("$", "").replace(",", ""))
            except ValueError:
                await update.message.reply_text("Couldn't parse that as a number. Try again from the bill.")
                return True
        elif field == "due_day":
            try:
                text = int(text)
            except ValueError:
                await update.message.reply_text("Need a number 1-31. Try again from the bill.")
                return True

        with db() as conn:
            conn.execute(f"UPDATE bills SET {field} = ? WHERE id = ? AND chat_id = ?",
                         (text, bill_id, chat_id))

        await update.message.reply_text(
            f"✅ Updated.",
            reply_markup=bill_detail_kb(bill_id, False),
        )
        return True

    return False
