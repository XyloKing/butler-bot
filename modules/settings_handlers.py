# Butler Bot
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
Settings text/callback handlers for schedule editing.
"""
import json
from telegram import Update
from telegram.ext import ContextTypes

from database import db
from keyboards import settings_kb, onboard_days_kb


async def handle_settings_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for settings edits."""
    awaiting = context.user_data.get("awaiting")
    if not awaiting or not awaiting.startswith("settings"):
        return False

    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if awaiting == "settings_shift_type":
        context.user_data["awaiting"] = None
        with db() as conn:
            conn.execute("UPDATE shifts SET shift_type = ? WHERE chat_id = ?", (text, chat_id))
        await update.message.reply_text(
            f"✅ Shift updated to {text}",
            reply_markup=settings_kb(),
        )
        return True

    return False


async def handle_settings_day_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle day selection for schedule editing (reuses onboard:day and onboard:days_done)."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data
    parts = data.split(":")

    editing = context.user_data.get("settings_editing")
    if not editing:
        return  # Not in settings edit mode

    action = parts[1] if len(parts) > 1 else ""

    if action == "day":
        day_num = int(parts[2])
        selected = context.user_data.get("settings_selected_days", [])
        if day_num in selected:
            selected.remove(day_num)
        else:
            selected.append(day_num)
        context.user_data["settings_selected_days"] = selected
        await query.edit_message_reply_markup(reply_markup=onboard_days_kb(selected))

    elif action == "days_done":
        selected = sorted(context.user_data.get("settings_selected_days", []))
        week_field = "week1_days" if editing == "week1" else "week2_days"

        with db() as conn:
            conn.execute(
                f"UPDATE shifts SET {week_field} = ? WHERE chat_id = ?",
                (json.dumps(selected), chat_id),
            )

        day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
        # Display in Sun-Sat order
        sun_sat = [6, 0, 1, 2, 3, 4, 5]
        ordered = [d for d in sun_sat if d in selected]
        days_str = ", ".join(day_names[d] for d in ordered)
        week_label = "Week 1" if editing == "week1" else "Week 2"

        context.user_data.pop("settings_editing", None)
        context.user_data.pop("settings_selected_days", None)

        await query.edit_message_text(
            f"✅ {week_label} updated: {days_str}",
            reply_markup=settings_kb(),
        )
