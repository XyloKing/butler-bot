"""
📒 Notes module.
Quick-capture notes attachable to any entity.
"""
from telegram import Update
from telegram.ext import ContextTypes

from database import db
from keyboards import notes_list_kb, back_to_menu_kb

AWAITING_NOTE = "note_content"


async def notes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all notes:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "view":
        await _show_notes_list(query, chat_id)

    elif action == "add":
        # notes:add:category or notes:add:category:ref_id
        category = parts[2] if len(parts) > 2 else "general"
        ref_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
        context.user_data["note_category"] = category
        context.user_data["note_ref_id"] = ref_id
        context.user_data["awaiting"] = AWAITING_NOTE
        await query.edit_message_text("📒 Type your note:")

    elif action == "detail":
        note_id = int(parts[2]) if len(parts) > 2 else None
        await _show_note_detail(query, chat_id, note_id)

    elif action == "delete":
        note_id = int(parts[2]) if len(parts) > 2 else None
        with db() as conn:
            conn.execute("DELETE FROM notes WHERE id = ? AND chat_id = ?", (note_id, chat_id))
        await query.edit_message_text("Note deleted.", reply_markup=back_to_menu_kb())


async def _show_notes_list(query, chat_id):
    notes = _get_notes(chat_id)
    if not notes:
        await query.edit_message_text(
            "📒 No notes yet.\n\nTap below to add one, or use 📒 from any item.",
            reply_markup=notes_list_kb([]),
        )
        return

    text = f"📒 NOTES ({len(notes)})\n\nTap to view:"
    await query.edit_message_text(text, reply_markup=notes_list_kb(notes))


async def _show_note_detail(query, chat_id, note_id):
    with db() as conn:
        note = conn.execute("SELECT * FROM notes WHERE id = ? AND chat_id = ?",
                            (note_id, chat_id)).fetchone()
    if not note:
        await query.edit_message_text("Note not found.", reply_markup=back_to_menu_kb())
        return

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    cat = note["category"] or "general"
    text = (
        f"📒 Note ({cat})\n"
        f"Created: {note['created_at']}\n\n"
        f"{note['content']}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Delete", callback_data=f"notes:delete:{note_id}")],
        [InlineKeyboardButton("⬅️ Notes", callback_data="notes:view")],
    ])
    await query.edit_message_text(text, reply_markup=kb)


def _get_notes(chat_id, limit=20) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM notes WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


async def handle_note_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for note creation."""
    awaiting = context.user_data.get("awaiting")
    if awaiting != AWAITING_NOTE:
        return False

    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    category = context.user_data.pop("note_category", "general")
    ref_id = context.user_data.pop("note_ref_id", None)
    context.user_data["awaiting"] = None

    with db() as conn:
        conn.execute(
            "INSERT INTO notes (chat_id, category, ref_id, content) VALUES (?, ?, ?, ?)",
            (chat_id, category, ref_id, text),
        )

    await update.message.reply_text(
        f"📒 Saved.",
        reply_markup=back_to_menu_kb(),
    )
    return True
