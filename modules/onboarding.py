"""
Onboarding flow — button-driven questionnaire.
Collects: work schedule, partners, bills, car, credentials, meds.
Designed so ANYONE can onboard (not just the original user).
"""
import json
from telegram import Update, CallbackQuery
from telegram.ext import ContextTypes, ConversationHandler

from database import db, ensure_user, update_user, get_user
from keyboards import (
    onboard_welcome_kb, onboard_shift_type_kb, onboard_days_kb,
    onboard_section_done_kb, onboard_yes_no_kb, main_menu_kb,
)

# Conversation states for text input steps
AWAITING_NAME = "onboard_name"
AWAITING_PARTNER_NAME = "onboard_partner_name"
AWAITING_BILL_NAME = "onboard_bill_name"
AWAITING_BILL_AMOUNT = "onboard_bill_amount"
AWAITING_CAR_DESC = "onboard_car_desc"
AWAITING_CAR_DATE = "onboard_car_date"
AWAITING_CRED_NAME = "onboard_cred_name"
AWAITING_CRED_EXPIRY = "onboard_cred_expiry"
AWAITING_MED_NAME = "onboard_med_name"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start — begin onboarding or show menu."""
    chat_id = update.effective_chat.id
    name = update.effective_user.first_name
    is_onboarded = ensure_user(chat_id, name)

    if is_onboarded:
        await update.message.reply_text(
            f"Welcome back, {name}. 🫡\n\nWhat do you need?",
            reply_markup=main_menu_kb(),
        )
    else:
        await update.message.reply_text(
            f"Yo {name}. 👋\n\n"
            "I'm your personal butler — I'll keep track of your bills, "
            "dates, car stuff, credentials, meds, and more.\n\n"
            "I work with buttons so you barely have to type. "
            "Let's get you set up real quick.",
            reply_markup=onboard_welcome_kb(),
        )


async def onboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all onboard:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data  # e.g. "onboard:start", "onboard:shift:12p-12a"
    parts = data.split(":")

    action = parts[1] if len(parts) > 1 else ""

    # ── Welcome ──────────────────────────────────────
    if action == "start":
        update_user(chat_id, onboard_step="name", onboard_data=json.dumps({}))
        await query.edit_message_text(
            "First — what should I call you?\n\n"
            "(Just type your name or nickname)",
        )
        context.user_data["awaiting"] = AWAITING_NAME
        return

    if action == "skip":
        update_user(chat_id, onboarded=1)
        await query.edit_message_text(
            "No problem — you can set everything up later from the menu.\n\n"
            "Tap /menu anytime.",
            reply_markup=main_menu_kb(),
        )
        return

    # ── Shift Type ───────────────────────────────────
    if action == "shift":
        shift_type = parts[2] if len(parts) > 2 else "custom"
        user = get_user(chat_id)
        ob_data = json.loads(user["onboard_data"] or "{}")
        ob_data["shift_type"] = shift_type
        update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="shift_days")

        if shift_type == "custom":
            await query.edit_message_text(
                "What are your shift hours? (e.g. '3p-11p')\nJust type it out.",
            )
            context.user_data["awaiting"] = "onboard_custom_shift"
        else:
            await query.edit_message_text(
                "Which days do you usually work?\nTap to select, then hit Done.\n\n"
                "(If you rotate, pick your Week 1 days first)",
                reply_markup=onboard_days_kb([]),
            )
        return

    # ── Day Selection (multi-select) ─────────────────
    if action == "day":
        day_num = int(parts[2])
        user = get_user(chat_id)
        ob_data = json.loads(user["onboard_data"] or "{}")
        selected = ob_data.get("selected_days", [])

        if day_num in selected:
            selected.remove(day_num)
        else:
            selected.append(day_num)

        ob_data["selected_days"] = selected
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        await query.edit_message_reply_markup(reply_markup=onboard_days_kb(selected))
        return

    if action == "days_done":
        user = get_user(chat_id)
        ob_data = json.loads(user["onboard_data"] or "{}")
        selected = ob_data.get("selected_days", [])

        if not ob_data.get("week1_days"):
            # First pass = week 1
            ob_data["week1_days"] = sorted(selected)
            ob_data["selected_days"] = []
            update_user(chat_id, onboard_data=json.dumps(ob_data))
            await query.edit_message_text(
                "Got it. Do you have a Week 2 rotation with different days?",
                reply_markup=onboard_yes_no_kb("onboard:has_week2"),
            )
        else:
            # Second pass = week 2
            ob_data["week2_days"] = sorted(selected)
            ob_data.pop("selected_days", None)
            update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="partners_intro")

            # Save shift to DB
            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO shifts (chat_id, shift_type, week1_days, week2_days) "
                    "VALUES (?, ?, ?, ?)",
                    (chat_id, ob_data.get("shift_type", "custom"),
                     json.dumps(ob_data["week1_days"]), json.dumps(ob_data["week2_days"])),
                )

            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            w1 = ", ".join(day_names[d] for d in ob_data["week1_days"])
            w2 = ", ".join(day_names[d] for d in ob_data["week2_days"])
            await query.edit_message_text(
                f"Schedule saved.\n"
                f"  Week 1: {w1}\n"
                f"  Week 2: {w2}\n\n"
                "Next up: people and relationships.",
                reply_markup=onboard_section_done_kb("partners_intro"),
            )
        return

    if action == "has_week2":
        answer = parts[2] if len(parts) > 2 else "no"
        user = get_user(chat_id)
        ob_data = json.loads(user["onboard_data"] or "{}")

        if answer == "yes":
            ob_data["selected_days"] = []
            update_user(chat_id, onboard_data=json.dumps(ob_data))
            await query.edit_message_text(
                "Pick your Week 2 days:",
                reply_markup=onboard_days_kb([]),
            )
        else:
            ob_data["week2_days"] = ob_data.get("week1_days", [])
            update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="partners_intro")

            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO shifts (chat_id, shift_type, week1_days, week2_days) "
                    "VALUES (?, ?, ?, ?)",
                    (chat_id, ob_data.get("shift_type", "custom"),
                     json.dumps(ob_data["week1_days"]), json.dumps(ob_data["week2_days"])),
                )

            await query.edit_message_text(
                "Schedule saved — same days every week.\n\n"
                "Next: people and relationships.",
                reply_markup=onboard_section_done_kb("partners_intro"),
            )
        return

    # ── Partners Intro ───────────────────────────────
    if action == "partners_intro":
        await query.edit_message_text(
            "Want to add any partners or important people?\n"
            "I'll track birthdays, anniversaries, and help you schedule dates.\n\n"
            "You can always add more later.",
            reply_markup=onboard_yes_no_kb("onboard:add_partners"),
        )
        return

    if action == "add_partners":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            await query.edit_message_text(
                "Type their name (or nickname):",
            )
            context.user_data["awaiting"] = AWAITING_PARTNER_NAME
        else:
            update_user(chat_id, onboard_step="bills_intro")
            await query.edit_message_text(
                "No worries. Next: bills and money.",
                reply_markup=onboard_section_done_kb("bills_intro"),
            )
        return

    if action == "another_partner":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            await query.edit_message_text("Type their name:")
            context.user_data["awaiting"] = AWAITING_PARTNER_NAME
        else:
            update_user(chat_id, onboard_step="bills_intro")
            await query.edit_message_text(
                "People saved. Next: bills and money.",
                reply_markup=onboard_section_done_kb("bills_intro"),
            )
        return

    # ── Bills Intro ──────────────────────────────────
    if action == "bills_intro":
        await query.edit_message_text(
            "Want to add your bills now?\n"
            "I'll remind you on payday and nag until they're paid.\n\n"
            "You can always add more later.",
            reply_markup=onboard_yes_no_kb("onboard:add_bills"),
        )
        return

    if action == "add_bills":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            await query.edit_message_text("Bill name? (e.g. 'Mortgage', 'PECO')")
            context.user_data["awaiting"] = AWAITING_BILL_NAME
        else:
            update_user(chat_id, onboard_step="car_intro")
            await query.edit_message_text(
                "Alright. Next: car and vehicle stuff.",
                reply_markup=onboard_section_done_kb("car_intro"),
            )
        return

    if action == "another_bill":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            await query.edit_message_text("Bill name?")
            context.user_data["awaiting"] = AWAITING_BILL_NAME
        else:
            update_user(chat_id, onboard_step="car_intro")
            await query.edit_message_text(
                "Bills saved. Next: car stuff.",
                reply_markup=onboard_section_done_kb("car_intro"),
            )
        return

    # ── Car Intro ────────────────────────────────────
    if action == "car_intro":
        await query.edit_message_text(
            "Got any car maintenance to track?\n"
            "(Oil changes, inspections, registration, etc.)",
            reply_markup=onboard_yes_no_kb("onboard:add_car"),
        )
        return

    if action == "add_car":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            await query.edit_message_text("What's the item? (e.g. 'Oil change', 'State inspection')")
            context.user_data["awaiting"] = AWAITING_CAR_DESC
        else:
            update_user(chat_id, onboard_step="creds_intro")
            await query.edit_message_text(
                "No problem. Next: professional credentials.",
                reply_markup=onboard_section_done_kb("creds_intro"),
            )
        return

    if action == "another_car":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            await query.edit_message_text("What's the item?")
            context.user_data["awaiting"] = AWAITING_CAR_DESC
        else:
            update_user(chat_id, onboard_step="creds_intro")
            await query.edit_message_text(
                "Car items saved. Next: credentials.",
                reply_markup=onboard_section_done_kb("creds_intro"),
            )
        return

    # ── Credentials Intro ────────────────────────────
    if action == "creds_intro":
        await query.edit_message_text(
            "Any professional licenses or certifications to track?\n"
            "(License numbers, expiry dates, CEU requirements)",
            reply_markup=onboard_yes_no_kb("onboard:add_creds"),
        )
        return

    if action == "add_creds":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            await query.edit_message_text("Credential name? (e.g. 'RRT License', 'BLS', 'ACLS')")
            context.user_data["awaiting"] = AWAITING_CRED_NAME
        else:
            update_user(chat_id, onboard_step="meds_intro")
            await query.edit_message_text(
                "Got it. Last one: medications.",
                reply_markup=onboard_section_done_kb("meds_intro"),
            )
        return

    if action == "another_cred":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            await query.edit_message_text("Credential name?")
            context.user_data["awaiting"] = AWAITING_CRED_NAME
        else:
            update_user(chat_id, onboard_step="meds_intro")
            await query.edit_message_text(
                "Credentials saved. Last one: medications.",
                reply_markup=onboard_section_done_kb("meds_intro"),
            )
        return

    # ── Meds Intro ───────────────────────────────────
    if action == "meds_intro":
        await query.edit_message_text(
            "Any daily medications to remind you about?\n"
            "I'll check in until you confirm you took them.",
            reply_markup=onboard_yes_no_kb("onboard:add_meds"),
        )
        return

    if action == "add_meds":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            await query.edit_message_text("Medication name?")
            context.user_data["awaiting"] = AWAITING_MED_NAME
        else:
            await _finish_onboarding(query, chat_id)
        return

    if action == "another_med":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            await query.edit_message_text("Medication name?")
            context.user_data["awaiting"] = AWAITING_MED_NAME
        else:
            await _finish_onboarding(query, chat_id)
        return

    # ── Finish ───────────────────────────────────────
    if action == "finish":
        await _finish_onboarding(query, chat_id)
        return


async def _finish_onboarding(query: CallbackQuery, chat_id: int):
    update_user(chat_id, onboarded=1, onboard_step=None)
    await query.edit_message_text(
        "You're all set. 🫡\n\n"
        "I'll start keeping track of everything.\n"
        "Tap /menu anytime — or I'll check in with you on schedule.\n\n"
        "You can always add or change things from the menu.",
        reply_markup=main_menu_kb(),
    )


async def handle_onboard_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handle text messages during onboarding.
    Returns True if the message was consumed, False if it should be passed on.
    """
    awaiting = context.user_data.get("awaiting")
    if not awaiting or not awaiting.startswith("onboard"):
        return False

    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    user = get_user(chat_id)
    ob_data = json.loads(user["onboard_data"] or "{}")

    # ── Name ─────────────────────────────────────────
    if awaiting == AWAITING_NAME:
        update_user(chat_id, display_name=text, onboard_step="shift_type")
        ob_data["name"] = text
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"Nice to meet you, {text}.\n\n"
            "What kind of shifts do you work?",
            reply_markup=onboard_shift_type_kb(),
        )
        return True

    # ── Custom Shift ─────────────────────────────────
    if awaiting == "onboard_custom_shift":
        ob_data["shift_type"] = text
        update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="shift_days")
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"Got it: {text}\n\nWhich days do you usually work? Tap to select:",
            reply_markup=onboard_days_kb([]),
        )
        return True

    # ── Partner Name ─────────────────────────────────
    if awaiting == AWAITING_PARTNER_NAME:
        with db() as conn:
            conn.execute(
                "INSERT INTO partners (chat_id, name) VALUES (?, ?)",
                (chat_id, text),
            )
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"Added {text} 💜\n\nAnother person?",
            reply_markup=onboard_yes_no_kb("onboard:another_partner"),
        )
        return True

    # ── Bill Name ────────────────────────────────────
    if awaiting == AWAITING_BILL_NAME:
        ob_data["pending_bill_name"] = text
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        context.user_data["awaiting"] = AWAITING_BILL_AMOUNT
        await update.message.reply_text(
            f"How much is {text}? (Just the number, or type 'skip')",
        )
        return True

    # ── Bill Amount ──────────────────────────────────
    if awaiting == AWAITING_BILL_AMOUNT:
        bill_name = ob_data.pop("pending_bill_name", "Unknown")
        amount = None
        if text.lower() != "skip":
            try:
                amount = float(text.replace("$", "").replace(",", ""))
            except ValueError:
                amount = None

        with db() as conn:
            conn.execute(
                "INSERT INTO bills (chat_id, name, amount) VALUES (?, ?, ?)",
                (chat_id, bill_name, amount),
            )
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        context.user_data["awaiting"] = None

        amt_str = f" (${amount:,.0f})" if amount else ""
        await update.message.reply_text(
            f"Added {bill_name}{amt_str} 💸\n\nAnother bill?",
            reply_markup=onboard_yes_no_kb("onboard:another_bill"),
        )
        return True

    # ── Car Description ──────────────────────────────
    if awaiting == AWAITING_CAR_DESC:
        ob_data["pending_car_desc"] = text
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        context.user_data["awaiting"] = AWAITING_CAR_DATE
        await update.message.reply_text(
            f"When is '{text}' due? (e.g. '2026-05-18' or 'May 2026')",
        )
        return True

    # ── Car Date ─────────────────────────────────────
    if awaiting == AWAITING_CAR_DATE:
        car_desc = ob_data.pop("pending_car_desc", "Car item")
        # Try to parse date loosely
        due_date = _parse_date_loosely(text)

        with db() as conn:
            conn.execute(
                "INSERT INTO car_events (chat_id, event_type, description, due_date) VALUES (?, ?, ?, ?)",
                (chat_id, "custom", car_desc, due_date),
            )
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"Added: {car_desc} — due {due_date} 🚗\n\nAnother car item?",
            reply_markup=onboard_yes_no_kb("onboard:another_car"),
        )
        return True

    # ── Credential Name ──────────────────────────────
    if awaiting == AWAITING_CRED_NAME:
        ob_data["pending_cred_name"] = text
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        context.user_data["awaiting"] = AWAITING_CRED_EXPIRY
        await update.message.reply_text(
            f"When does '{text}' expire? (e.g. '2027-06-01' or 'June 2027')",
        )
        return True

    # ── Credential Expiry ────────────────────────────
    if awaiting == AWAITING_CRED_EXPIRY:
        cred_name = ob_data.pop("pending_cred_name", "Credential")
        expiry = _parse_date_loosely(text)

        with db() as conn:
            conn.execute(
                "INSERT INTO credentials (chat_id, name, expiry_date) VALUES (?, ?, ?)",
                (chat_id, cred_name, expiry),
            )
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"Added: {cred_name} — expires {expiry} 🎓\n\nAnother credential?",
            reply_markup=onboard_yes_no_kb("onboard:another_cred"),
        )
        return True

    # ── Medication Name ──────────────────────────────
    if awaiting == AWAITING_MED_NAME:
        with db() as conn:
            conn.execute(
                "INSERT INTO medications (chat_id, name) VALUES (?, ?)",
                (chat_id, text),
            )
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"Added: {text} 💊\n\nAnother medication?",
            reply_markup=onboard_yes_no_kb("onboard:another_med"),
        )
        return True

    return False


def _parse_date_loosely(text: str) -> str:
    """Best-effort date parsing. Returns ISO date string."""
    from datetime import datetime
    import re

    text = text.strip()

    # Strip ordinal suffixes (1st, 2nd, 3rd, 4th, 29th, etc.)
    text = re.sub(r'(\d+)(st|nd|rd|th)\b', r'\1', text, flags=re.IGNORECASE)

    # Try ISO format first
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d")
    except ValueError:
        pass

    # Try "Month Year" or "Month Day, Year"
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    text_lower = text.lower()
    for mname, mnum in months.items():
        if mname in text_lower:
            # Find year
            year_match = re.search(r"20\d{2}", text)
            year = int(year_match.group()) if year_match else datetime.now().year
            # Find day
            day_match = re.search(r"\b(\d{1,2})\b", text.replace(str(year), ""))
            day = int(day_match.group()) if day_match else 1
            try:
                return datetime(year, mnum, day).strftime("%Y-%m-%d")
            except ValueError:
                return datetime(year, mnum, 1).strftime("%Y-%m-%d")

    # Fallback: return as-is
    return text
