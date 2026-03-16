"""
💜 People & Dates module.
Partner tracking, birthdays, anniversaries, date scheduling.
"""
from datetime import date
from telegram import Update
from telegram.ext import ContextTypes

from database import db
from helpers import today, days_until, friendly_date
from keyboards import (
    partners_list_kb, partner_detail_kb, back_to_menu_kb,
)

AWAITING_PARTNER_NAME = "partner_name"
AWAITING_PARTNER_EMOJI = "partner_emoji"
AWAITING_DATE_VALUE = "partner_date_value"


async def partners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all partners:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    item_id = int(parts[-1]) if len(parts) > 2 and parts[-1].isdigit() else None

    if action == "view":
        await _show_partners_list(query, chat_id)

    elif action == "detail":
        await _show_partner_detail(query, chat_id, item_id)

    elif action == "add":
        await query.edit_message_text("What's their name?")
        context.user_data["awaiting"] = AWAITING_PARTNER_NAME

    elif action == "adddate":
        date_type = parts[2] if len(parts) > 2 else "custom"
        partner_id = int(parts[3]) if len(parts) > 3 else None
        context.user_data["pending_date_type"] = date_type
        context.user_data["pending_date_partner"] = partner_id
        context.user_data["awaiting"] = AWAITING_DATE_VALUE

        if date_type == "birthday":
            await query.edit_message_text("When's their birthday? (MM-DD or full date)")
        elif date_type == "anniversary":
            await query.edit_message_text("Anniversary date? (YYYY-MM-DD or MM-DD)")
        else:
            await query.edit_message_text("Date? (YYYY-MM-DD or MM-DD for recurring)")

    elif action == "schedule":
        # Show available days this week for a date
        from helpers import next_payday, is_work_day
        import json
        with db() as conn:
            partner = conn.execute("SELECT * FROM partners WHERE id = ? AND chat_id = ?",
                                   (item_id, chat_id)).fetchone()
            shift = conn.execute("SELECT * FROM shifts WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
                                 (chat_id,)).fetchone()

        name = partner["name"] if partner else "them"
        d = today()

        # Find free evenings this week
        free_days = []
        from datetime import timedelta
        for i in range(7):
            check = d + timedelta(days=i)
            is_work = False
            if shift and shift["week1_days"]:
                w1 = json.loads(shift["week1_days"])
                w2 = json.loads(shift["week2_days"] or "[]") or w1
                try:
                    anchor = shift["anchor_date"] or "2026-03-30"
                except (IndexError, KeyError):
                    anchor = "2026-03-30"
                is_work = is_work_day(check, anchor, w1, w2)
            if not is_work:
                free_days.append(check)

        if free_days:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            rows = []
            for fd in free_days[:5]:
                label = fd.strftime("%A %m/%d")
                rows.append([InlineKeyboardButton(
                    f"📅 {label}",
                    callback_data=f"partners:booked:{item_id}:{fd.isoformat()}"
                )])
            rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"partners:detail:{item_id}")])
            await query.edit_message_text(
                f"Free days this week for {name}:\n(Tap to log a date)",
                reply_markup=InlineKeyboardMarkup(rows),
            )
        else:
            await query.edit_message_text(
                f"Looks like you're working every day this week. 😅\nTry next week?",
                reply_markup=partner_detail_kb(item_id),
            )

    elif action == "booked":
        partner_id = int(parts[2]) if len(parts) > 2 else None
        date_str = parts[3] if len(parts) > 3 else None
        with db() as conn:
            partner = conn.execute("SELECT name FROM partners WHERE id = ?", (partner_id,)).fetchone()
            conn.execute(
                "INSERT INTO partner_dates (partner_id, chat_id, date_type, label, date_value, recurring) "
                "VALUES (?, ?, 'date_night', 'Date Night', ?, 0)",
                (partner_id, chat_id, date_str),
            )
        name = partner["name"] if partner else "them"
        await query.edit_message_text(
            f"💜 Date with {name} on {date_str} — locked in.\n\nI'll remind you the day before.",
            reply_markup=partner_detail_kb(partner_id),
        )

    elif action == "editfield":
        field = parts[2] if len(parts) > 2 else "name"
        pid = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else item_id
        from modules.field_editor import start_field_edit
        await start_field_edit(update, context, "partners", pid, field)

    elif action == "delete":
        from keyboards import confirm_delete_kb
        with db() as conn:
            partner = conn.execute("SELECT name FROM partners WHERE id = ? AND chat_id = ?",
                                   (item_id, chat_id)).fetchone()
        name = partner["name"] if partner else "this person"
        await query.edit_message_text(f"Remove {name}?", reply_markup=confirm_delete_kb("partners", item_id))

    elif action == "confirm_delete":
        with db() as conn:
            conn.execute("DELETE FROM partner_dates WHERE partner_id = ? AND chat_id = ?", (item_id, chat_id))
            conn.execute("DELETE FROM partners WHERE id = ? AND chat_id = ?", (item_id, chat_id))
        await query.edit_message_text("Removed.", reply_markup=back_to_menu_kb())


async def _show_partners_list(query, chat_id):
    partners = _get_partners(chat_id)
    if not partners:
        await query.edit_message_text(
            "No people added yet.\n\nTap below to add someone.",
            reply_markup=partners_list_kb([]),
        )
        return

    text = "💜 PEOPLE & DATES\n\nTap someone for details:"
    await query.edit_message_text(text, reply_markup=partners_list_kb(partners))


async def _show_partner_detail(query, chat_id, partner_id):
    with db() as conn:
        partner = conn.execute("SELECT * FROM partners WHERE id = ? AND chat_id = ?",
                               (partner_id, chat_id)).fetchone()
        dates = conn.execute(
            "SELECT * FROM partner_dates WHERE partner_id = ? AND chat_id = ? ORDER BY date_value",
            (partner_id, chat_id)
        ).fetchall()

    if not partner:
        await query.edit_message_text("Person not found.", reply_markup=back_to_menu_kb())
        return

    emoji = partner["emoji"] or "💜"
    lines = [
        f"{emoji} {partner['name']}",
        f"Target: ~{partner['target_dates_per_month']} dates/month",
        "",
    ]

    if dates:
        lines.append("Important dates:")
        d = today()
        for pd_row in dates:
            dv = pd_row["date_value"]
            label = pd_row["label"] or pd_row["date_type"]
            if len(dv) == 5:  # MM-DD recurring
                try:
                    this_year = date(d.year, int(dv[:2]), int(dv[3:]))
                    if this_year < d:
                        this_year = date(d.year + 1, int(dv[:2]), int(dv[3:]))
                    lines.append(f"  🔄 {label}: {dv} — {friendly_date(this_year)}")
                except ValueError:
                    lines.append(f"  🔄 {label}: {dv}")
            else:
                try:
                    target = date.fromisoformat(dv)
                    lines.append(f"  📅 {label}: {friendly_date(target)}")
                except ValueError:
                    lines.append(f"  📅 {label}: {dv}")
    else:
        lines.append("No dates added yet.")

    await query.edit_message_text("\n".join(lines), reply_markup=partner_detail_kb(partner_id))


def _get_partners(chat_id) -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM partners WHERE chat_id = ? ORDER BY name", (chat_id,)).fetchall()
    return [dict(r) for r in rows]


async def handle_partner_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for partner operations."""
    awaiting = context.user_data.get("awaiting")
    if not awaiting or not awaiting.startswith("partner"):
        return False

    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if awaiting == AWAITING_PARTNER_NAME:
        with db() as conn:
            cursor = conn.execute(
                "INSERT INTO partners (chat_id, name) VALUES (?, ?)",
                (chat_id, text),
            )
            partner_id = cursor.lastrowid
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"Added {text} 💜",
            reply_markup=partner_detail_kb(partner_id),
        )
        return True

    if awaiting == AWAITING_DATE_VALUE:
        date_type = context.user_data.pop("pending_date_type", "custom")
        partner_id = context.user_data.pop("pending_date_partner", None)
        context.user_data["awaiting"] = None

        # Normalize date
        date_val = text.strip()
        recurring = 1 if len(date_val) == 5 else 0  # MM-DD = recurring

        with db() as conn:
            conn.execute(
                "INSERT INTO partner_dates (partner_id, chat_id, date_type, date_value, recurring) "
                "VALUES (?, ?, ?, ?, ?)",
                (partner_id, chat_id, date_type, date_val, recurring),
            )

        await update.message.reply_text(
            f"✅ Saved {date_type}: {date_val}",
            reply_markup=partner_detail_kb(partner_id),
        )
        return True

    if awaiting == "partner_edit_name":
        partner_id = context.user_data.pop("edit_partner_id", None)
        context.user_data["awaiting"] = None
        if text.lower() != "skip" and partner_id:
            with db() as conn:
                conn.execute("UPDATE partners SET name = ? WHERE id = ? AND chat_id = ?",
                             (text, partner_id, chat_id))
        partners = _get_partners(chat_id)
        await update.message.reply_text("Updated.", reply_markup=partners_list_kb(partners))
        return True

    return False
