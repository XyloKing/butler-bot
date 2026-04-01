# Butler Bot
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
💊 Medications module.
Daily check-ins, aggressive until confirmed taken.
"""
from telegram import Update
from telegram.ext import ContextTypes

from database import db
from keyboards import meds_list_kb, med_detail_kb, back_to_menu_kb, confirm_delete_kb

AWAITING_MED_NAME = "med_name"
AWAITING_MED_DOSAGE = "med_dosage"
AWAITING_MED_EDIT = "med_edit"


async def meds_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all meds:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    item_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

    if action == "view":
        await _show_meds_list(query, chat_id)

    elif action == "detail":
        await _show_med_detail(query, chat_id, item_id)

    elif action == "taken" or action == "all_taken":
        with db() as conn:
            if action == "all_taken":
                conn.execute("UPDATE medications SET taken_today = 1 WHERE chat_id = ?", (chat_id,))
            else:
                # From today view, mark all
                conn.execute("UPDATE medications SET taken_today = 1 WHERE chat_id = ?", (chat_id,))
        await query.edit_message_text(
            "💊 All meds marked as taken. Nice work. 🫡",
            reply_markup=back_to_menu_kb(),
        )

    elif action == "take":
        with db() as conn:
            conn.execute("UPDATE medications SET taken_today = 1 WHERE id = ? AND chat_id = ?",
                         (item_id, chat_id))
            med = conn.execute("SELECT name FROM medications WHERE id = ?", (item_id,)).fetchone()
        name = med["name"] if med else "Med"
        await query.edit_message_text(f"✅ {name} taken.")
        await _show_meds_list(query, chat_id, send_new=True)

    elif action == "untake":
        with db() as conn:
            conn.execute("UPDATE medications SET taken_today = 0 WHERE id = ? AND chat_id = ?",
                         (item_id, chat_id))
        await _show_med_detail(query, chat_id, item_id)

    elif action == "add":
        context.user_data["awaiting"] = AWAITING_MED_NAME
        await query.edit_message_text("Medication name?")

    elif action == "editfield":
        field = parts[3] if len(parts) > 3 else "name"
        from modules.field_editor import start_field_edit
        await start_field_edit(update, context, "meds", item_id, field)

    elif action == "setfreq":
        # meds:setfreq:{id}:{freq_val}
        med_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        freq_val = parts[3] if len(parts) > 3 else "daily"
        if med_id:
            with db() as conn:
                conn.execute(
                    "UPDATE medications SET frequency = ? WHERE id = ? AND chat_id = ?",
                    (freq_val, med_id, chat_id),
                )
            await query.edit_message_text(
                f"✅ Frequency updated to: {freq_val.replace('_', ' ')}",
                reply_markup=med_detail_kb(med_id, False),
            )

    elif action == "delete":
        with db() as conn:
            med = conn.execute("SELECT name FROM medications WHERE id = ? AND chat_id = ?",
                               (item_id, chat_id)).fetchone()
        name = med["name"] if med else "this medication"
        await query.edit_message_text(f"Remove {name}?", reply_markup=confirm_delete_kb("meds", item_id))

    elif action == "confirm_delete":
        with db() as conn:
            conn.execute("DELETE FROM medications WHERE id = ? AND chat_id = ?", (item_id, chat_id))
        await query.edit_message_text("Removed.", reply_markup=back_to_menu_kb())


async def _show_meds_list(query, chat_id, send_new=False):
    meds = _get_meds(chat_id)
    if not meds:
        text = "💊 No medications tracked yet.\n\nTap below to add one."
    else:
        taken = sum(1 for m in meds if m["taken_today"])
        total = len(meds)
        if taken == total:
            status = "All taken today ✅"
        elif taken == 0:
            status = "⚠️ None taken yet"
        else:
            status = f"{taken}/{total} taken"
        text = f"💊 MEDICATIONS\n{status}\n\nTap to mark taken or edit:"
    kb = meds_list_kb(meds)
    if send_new:
        await query.message.reply_text(text, reply_markup=kb)
    else:
        await query.edit_message_text(text, reply_markup=kb)


async def _show_med_detail(query, chat_id, med_id):
    with db() as conn:
        med = conn.execute("SELECT * FROM medications WHERE id = ? AND chat_id = ?",
                           (med_id, chat_id)).fetchone()
    if not med:
        await query.edit_message_text("Medication not found.", reply_markup=back_to_menu_kb())
        return

    lines = [
        f"💊 {med['name']}",
    ]
    if med["dosage"]:
        lines.append(f"Dosage: {med['dosage']}")
    lines.append(f"Frequency: {med['frequency']}")
    lines.append(f"Today: {'✅ Taken' if med['taken_today'] else '⬜ Not taken'}")
    if med["refill_date"]:
        lines.append(f"Refill due: {med['refill_date']}")
    if med["notes"]:
        lines.append(f"📒 {med['notes']}")

    await query.edit_message_text("\n".join(lines), reply_markup=med_detail_kb(med_id, med["taken_today"]))


def _get_meds(chat_id) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM medications WHERE chat_id = ? ORDER BY name", (chat_id,)
        ).fetchall()
    return [dict(r) for r in rows]


async def handle_med_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for med operations."""
    awaiting = context.user_data.get("awaiting")
    if not awaiting or not awaiting.startswith("med"):
        return False

    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if awaiting == AWAITING_MED_NAME:
        context.user_data["new_med_name"] = text
        context.user_data["awaiting"] = AWAITING_MED_DOSAGE
        await update.message.reply_text(f"Dosage for {text}? (e.g. '20mg', or 'skip')")
        return True

    if awaiting == AWAITING_MED_DOSAGE:
        name = context.user_data.pop("new_med_name", "Med")
        dosage = text if text.lower() != "skip" else None
        context.user_data["awaiting"] = None

        with db() as conn:
            cursor = conn.execute(
                "INSERT INTO medications (chat_id, name, dosage) VALUES (?, ?, ?)",
                (chat_id, name, dosage),
            )
            med_id = cursor.lastrowid

        dosage_str = f" ({dosage})" if dosage else ""
        await update.message.reply_text(
            f"✅ Added: {name}{dosage_str}",
            reply_markup=med_detail_kb(med_id, False),
        )
        return True

    if awaiting == AWAITING_MED_EDIT:
        med_id = context.user_data.pop("edit_med_id", None)
        context.user_data["awaiting"] = None

        # Parse "Name Dosage" or just "Name"
        parts = text.rsplit(" ", 1)
        name = parts[0]
        dosage = parts[1] if len(parts) > 1 and any(c.isdigit() for c in parts[1]) else None

        with db() as conn:
            if dosage:
                conn.execute("UPDATE medications SET name = ?, dosage = ? WHERE id = ? AND chat_id = ?",
                             (name, dosage, med_id, chat_id))
            else:
                conn.execute("UPDATE medications SET name = ? WHERE id = ? AND chat_id = ?",
                             (name, med_id, chat_id))

        await update.message.reply_text("✅ Updated.", reply_markup=med_detail_kb(med_id, False))
        return True

    return False
