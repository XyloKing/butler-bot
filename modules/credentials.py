# Butler Bot
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
🎓 Professional Credentials module.
Low-maintenance — only surfaces when something's coming due.
Tracks license numbers, states, CEU progress, expiry dates.
"""
from datetime import date
from telegram import Update
from telegram.ext import ContextTypes

from database import db
from helpers import today, days_until, friendly_date, urgency_emoji
from keyboards import creds_list_kb, cred_detail_kb, back_to_menu_kb, confirm_delete_kb

AWAITING_CRED_NAME = "cred_name"
AWAITING_CRED_EXPIRY = "cred_expiry"
AWAITING_CRED_NUM = "cred_num"
AWAITING_CRED_STATE = "cred_state"
# Note: AWAITING_CRED_EDIT_FIELD and AWAITING_CRED_EDIT_VALUE removed — editing is now handled by field_editor


async def creds_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all creds:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    item_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

    if action == "view":
        await _show_creds_list(query, chat_id)

    elif action == "detail":
        await _show_cred_detail(query, chat_id, item_id)

    elif action == "add":
        context.user_data["awaiting"] = AWAITING_CRED_NAME
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✕ Cancel", callback_data="menu:main")]])
        await query.edit_message_text("Credential name? (e.g. 'RRT License', 'BLS', 'ACLS')", reply_markup=cancel_kb)


    elif action == "renewed":
        with db() as conn:
            conn.execute("UPDATE credentials SET renewed = 1 WHERE id = ? AND chat_id = ?",
                         (item_id, chat_id))
            cred = conn.execute("SELECT name FROM credentials WHERE id = ?", (item_id,)).fetchone()
        name = cred["name"] if cred else "Credential"
        await query.edit_message_text(f"✅ {name} marked as renewed.")
        await _show_creds_list(query, chat_id, send_new=True)

    elif action == "editfield":
        field = parts[3] if len(parts) > 3 else "name"
        from modules.field_editor import start_field_edit
        await start_field_edit(update, context, "creds", item_id, field)

    elif action == "delete":
        with db() as conn:
            cred = conn.execute("SELECT name FROM credentials WHERE id = ? AND chat_id = ?",
                                (item_id, chat_id)).fetchone()
        name = cred["name"] if cred else "this credential"
        await query.edit_message_text(f"Delete {name}?", reply_markup=confirm_delete_kb("creds", item_id))

    elif action == "confirm_delete":
        with db() as conn:
            conn.execute("DELETE FROM credentials WHERE id = ? AND chat_id = ?", (item_id, chat_id))
        import random
        await query.edit_message_text(random.choice(["Gone.", "Removed.", "Deleted."]), reply_markup=back_to_menu_kb())


async def _show_creds_list(query, chat_id, send_new=False):
    creds = _get_creds(chat_id)
    if not creds:
        text = "🎓 No credentials tracked yet.\n\nTap below to add one."
    else:
        d = today()
        expiring_soon = 0
        for c in creds:
            try:
                if not c["renewed"] and days_until(date.fromisoformat(c["expiry_date"])) <= 90:
                    expiring_soon += 1
            except (ValueError, TypeError):
                continue
        status = f"⚠️ {expiring_soon} expiring within 90 days" if expiring_soon else "All good ✅"
        text = f"🎓 PROFESSIONAL CREDENTIALS\n{status}\n\nTap for details:"
    kb = creds_list_kb(creds)
    if send_new:
        await query.message.reply_text(text, reply_markup=kb)
    else:
        await query.edit_message_text(text, reply_markup=kb)


async def _show_cred_detail(query, chat_id, cred_id):
    with db() as conn:
        cred = conn.execute("SELECT * FROM credentials WHERE id = ? AND chat_id = ?",
                            (cred_id, chat_id)).fetchone()
    if not cred:
        await query.edit_message_text("Credential not found.", reply_markup=back_to_menu_kb())
        return

    try:
        exp = date.fromisoformat(cred["expiry_date"])
    except (ValueError, TypeError):
        await query.edit_message_text("Bad date on this credential. Tap below to continue.", reply_markup=back_to_menu_kb())
        return
    delta = days_until(exp)
    urg = urgency_emoji(delta)

    lines = [
        f"🎓 {cred['name']}",
    ]
    if cred["credential_num"]:
        lines.append(f"License #: {cred['credential_num']}")
    if cred["state"]:
        lines.append(f"State: {cred['state']}")
    if cred["issuing_body"]:
        lines.append(f"Issuer: {cred['issuing_body']}")

    lines.append(f"Expires: {cred['expiry_date']} — {friendly_date(exp)}")
    lines.append(f"Status: {'✅ Renewed' if cred['renewed'] else f'{urg} Active'}")

    if cred["ceu_required"]:
        lines.append(f"CEUs: {cred['ceu_completed']}/{cred['ceu_required']}")

    if cred["renewal_url"]:
        lines.append(f"Renewal: {cred['renewal_url']}")
    if cred["notes"]:
        lines.append(f"📒 {cred['notes']}")

    await query.edit_message_text("\n".join(lines), reply_markup=cred_detail_kb(cred_id))


def _get_creds(chat_id) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM credentials WHERE chat_id = ? ORDER BY renewed, expiry_date",
            (chat_id,)
        ).fetchall()
    return [dict(r) for r in rows]


async def handle_cred_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for credential operations."""
    awaiting = context.user_data.get("awaiting")
    if not awaiting or not awaiting.startswith("cred"):
        return False

    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if awaiting == AWAITING_CRED_NAME:
        # Store in DB so it survives bot restarts
        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (chat_id, key, value) VALUES (?, 'pending_cred_name', ?)",
                (chat_id, text),
            )
        context.user_data["awaiting"] = None
        from keyboards import date_pick_month_kb
        await update.message.reply_text(
            f"📅 When does {text} expire?",
            reply_markup=date_pick_month_kb("creddp"),
        )
        return True

    return False


async def cred_datepick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle creddp:* callbacks for date picker during credential creation."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "cancel":
        await _show_creds_list(query, chat_id)

    elif action == "yr":
        year = int(parts[2]) if len(parts) > 2 else __import__('datetime').date.today().year
        from keyboards import date_pick_month_kb
        await query.edit_message_text("📅 When does it expire?", reply_markup=date_pick_month_kb("creddp", year))

    elif action == "month":
        month = int(parts[2]) if len(parts) > 2 else 1
        year = int(parts[3]) if len(parts) > 3 else __import__('datetime').date.today().year
        from keyboards import date_pick_day_kb
        await query.edit_message_text("📅 Pick the day:", reply_markup=date_pick_day_kb("creddp", month, year))

    elif action == "day":
        date_str = parts[2] if len(parts) > 2 else ""
        # Read from DB (survives restarts)
        with db() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE chat_id = ? AND key = 'pending_cred_name'",
                (chat_id,)
            ).fetchone()
            name = row["value"] if row else None
            conn.execute("DELETE FROM settings WHERE chat_id = ? AND key = 'pending_cred_name'", (chat_id,))
        context.user_data.pop("new_cred_name", None)
        if not name:
            await _show_creds_list(query, chat_id)
            return
        with db() as conn:
            cursor = conn.execute(
                "INSERT INTO credentials (chat_id, name, expiry_date) VALUES (?, ?, ?)",
                (chat_id, name, date_str),
            )
            cred_id = cursor.lastrowid
        await query.edit_message_text(
            f"✅ Added: {name} — expires {date_str}\n\n"
            "You can add license #, state, and CEU info from the detail view.",
            reply_markup=cred_detail_kb(cred_id),
        )
