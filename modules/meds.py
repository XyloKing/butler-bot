# Butler Bot
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
💊 Medications module.
Daily check-ins, aggressive until confirmed taken.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import db
from keyboards import meds_list_kb, med_detail_kb, back_to_menu_kb, confirm_delete_kb

AWAITING_MED_NAME = "med_name"
AWAITING_MED_DOSAGE = "med_dosage"
AWAITING_MED_EDIT = "med_edit"

STREAK_MESSAGES = {
    3: "💊 3 days in a row. That's a real habit forming.",
    7: "💊 One full week. Your body is thanking you.",
    14: "💊 Two weeks straight. Seriously impressive.",
    30: "💊 30 days. You're doing something most people can't.",
}


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
            conn.execute("UPDATE medications SET taken_today = 1 WHERE chat_id = ?", (chat_id,))
        msg = "💊 All meds marked as taken. Nice work. 🫡"
        streak_msg = _check_streak_celebration(chat_id)
        if streak_msg:
            msg += f"\n\n{streak_msg}"
        await query.edit_message_text(msg, reply_markup=back_to_menu_kb())

    elif action == "take":
        with db() as conn:
            conn.execute("UPDATE medications SET taken_today = 1 WHERE id = ? AND chat_id = ?",
                         (item_id, chat_id))
            med = conn.execute("SELECT name FROM medications WHERE id = ?", (item_id,)).fetchone()
            # Check if all meds are now taken
            remaining = conn.execute(
                "SELECT COUNT(*) as c FROM medications WHERE chat_id = ? AND taken_today = 0",
                (chat_id,),
            ).fetchone()
        name = med["name"] if med else "Med"
        if remaining and remaining["c"] == 0:
            streak_msg = _check_streak_celebration(chat_id)
            extra = f"\n\n{streak_msg}" if streak_msg else ""
            await query.edit_message_text(f"✅ {name} taken. All meds done! 🫡{extra}")
        else:
            await query.edit_message_text(random.choice([
                f"✅ {name} — done.",
                f"✅ {name} marked. Good.",
                f"💊 {name} — logged.",
                f"✅ Got it — {name} taken.",
            ]))
        await _show_meds_list(query, chat_id, send_new=True)

    elif action == "untake":
        with db() as conn:
            conn.execute("UPDATE medications SET taken_today = 0 WHERE id = ? AND chat_id = ?",
                         (item_id, chat_id))
        await _show_med_detail(query, chat_id, item_id)

    elif action == "add":
        context.user_data["awaiting"] = AWAITING_MED_NAME
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✕ Cancel", callback_data="menu:main")]])
        await query.edit_message_text("Medication name?", reply_markup=cancel_kb)

    elif action == "editfield":
        field = parts[3] if len(parts) > 3 else "name"
        from modules.field_editor import start_field_edit
        await start_field_edit(update, context, "meds", item_id, field)

    elif action == "setschedule":
        # meds:setschedule:{id}:{schedule}
        med_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        schedule = parts[3] if len(parts) > 3 else "daily"
        if med_id:
            with db() as conn:
                conn.execute(
                    "UPDATE medications SET schedule = ? WHERE id = ? AND chat_id = ?",
                    (schedule, med_id, chat_id),
                )
            # After schedule, ask frequency
            from keyboards import med_frequency_kb
            schedule_labels = {
                "morning": "morning", "midday": "midday", "evening": "evening",
                "bedtime": "bedtime", "prn": "as needed",
            }
            label = schedule_labels.get(schedule, schedule)
            await query.edit_message_text(
                f"✅ {label.title()}. How often do you take it?",
                reply_markup=med_frequency_kb(med_id),
            )

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
            freq_labels = {
                "daily": "Every day", "twice_daily": "Twice a day",
                "every_other": "Every other day", "weekly": "Weekly", "prn": "As needed",
            }
            label = freq_labels.get(freq_val, freq_val)
            await query.edit_message_text(
                f"✅ {label}. All set.",
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
        await query.edit_message_text(random.choice(["Gone.", "Removed.", "Deleted."]), reply_markup=back_to_menu_kb())


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
            status = "💊 Not yet — still here when you're ready"
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

        # Save name+dosage to DB now, then ask schedule via buttons
        with db() as conn:
            cursor = conn.execute(
                "INSERT INTO medications (chat_id, name, dosage) VALUES (?, ?, ?)",
                (chat_id, name, dosage),
            )
            med_id = cursor.lastrowid

        from keyboards import med_schedule_kb
        dosage_str = f" {dosage}" if dosage else ""
        await update.message.reply_text(
            f"Added {name}{dosage_str}. When do you take it?",
            reply_markup=med_schedule_kb(med_id),
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


def _check_streak_celebration(chat_id: int) -> str | None:
    """Return a celebration message if the user hit a streak milestone.
    Only celebrates — never guilts on miss."""
    with db() as conn:
        user = conn.execute(
            "SELECT med_streak FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    if not user:
        return None
    streak = (user["med_streak"] or 0) + 1  # +1 because today counts but reset hasn't run yet
    return STREAK_MESSAGES.get(streak)
