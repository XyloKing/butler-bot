# Butler Bot
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
📒 Notes module.
Quick-capture notes attachable to any entity.
Task breakdown helper for ADHD-friendly step-by-step guidance.
"""
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import db
from keyboards import notes_list_kb, back_to_menu_kb

AWAITING_NOTE = "note_content"

TASK_WORDS = {
    "need to", "have to", "gotta", "should", "clean", "organize", "fix",
    "sort out", "deal with", "call", "email", "pay", "renew", "schedule", "book",
}


def _sounds_like_task(text: str) -> bool:
    lower = text.lower()
    return len(text) > 20 and any(w in lower for w in TASK_WORDS)


def _break_into_steps(text: str) -> list[str]:
    """Generate simple first-step breakdowns for common task types."""
    lower = text.lower()

    if any(w in lower for w in ["tax", "taxes", "irs"]):
        return ["Find last year's return", "Gather W-2s and 1099s",
                "Open tax software or find a preparer", "Set a 1-hour block to start"]
    if any(w in lower for w in ["clean", "tidy", "organize"]):
        return ["Pick one surface or drawer to start", "Get a trash bag",
                "Set a 15-minute timer", "Put away one category at a time"]
    if any(w in lower for w in ["call", "phone", "contact"]):
        return ["Find the right phone number first",
                "Write down what you need to say", "Pick a time when you can actually call"]
    if any(w in lower for w in ["doctor", "dentist", "appointment", "schedule", "book"]):
        return ["Find the provider's number or website",
                "Check your schedule for open mornings", "Call or book online",
                "Add it to the bot"]
    if any(w in lower for w in ["pay", "bill", "renew"]):
        return ["Log in or find the account info", "Confirm the amount due",
                "Pay it", "Mark it done here"]

    return [
        "Define exactly what 'done' looks like",
        "Find the first physical action: what's the very first thing to touch or open?",
        "Do just that first thing — nothing else yet",
    ]


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
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✕ Cancel", callback_data="menu:main")]])
        await query.edit_message_text("📒 Type your note:", reply_markup=cancel_kb)

    elif action == "detail":
        note_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        await _show_note_detail(query, chat_id, note_id)

    elif action == "breakdown":
        note_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        if not note_id:
            return
        with db() as conn:
            note = conn.execute(
                "SELECT content FROM notes WHERE id = ? AND chat_id = ?",
                (note_id, chat_id),
            ).fetchone()
        if not note:
            await query.edit_message_text("Note not found.", reply_markup=back_to_menu_kb())
            return
        steps = _break_into_steps(note["content"])
        preview = note["content"][:50]
        lines = [f"📋 Breaking down: \"{preview}\"", ""]
        for i, step in enumerate(steps, 1):
            lines.append(f"  {i}. {step}")
        lines += ["", "Tap any step to add it as an appointment or reminder."]
        await query.edit_message_text("\n".join(lines), reply_markup=back_to_menu_kb())

    elif action == "delete":
        note_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
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
        cursor = conn.execute(
            "INSERT INTO notes (chat_id, category, ref_id, content) VALUES (?, ?, ?, ?)",
            (chat_id, category, ref_id, text),
        )
        note_id = cursor.lastrowid

    if _sounds_like_task(text):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔨 Break it down for me", callback_data=f"notes:breakdown:{note_id}")],
            [InlineKeyboardButton("📒 Just keep it as a note", callback_data="menu:main")],
        ])
        await update.message.reply_text(
            "Saved. That sounds like it might have a few steps — want me to break it down?",
            reply_markup=kb,
        )
    else:
        await update.message.reply_text(
            random.choice(["📒 Saved.", "📒 Got it.", "📒 Noted.", "📒 Logged."]),
            reply_markup=back_to_menu_kb(),
        )
    return True
