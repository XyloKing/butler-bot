# Butler Bot
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
Onboarding flow — button-driven questionnaire.
Collects: work schedule, partners, bills, car, credentials, meds.
Designed so ANYONE can onboard (not just the original user).

v2.1.0-onboard-overhaul:
- DB onboard_step is source of truth (survives bot restarts)
- Full input validation for all text fields
- Back buttons, skip buttons, progress indicators
- Duplicate detection for partners/bills/meds/credentials/car items
- Friendly, casual error messages
"""
import json
import logging
import re
import traceback
from datetime import date, datetime, timedelta

from telegram import Update, CallbackQuery
from telegram.ext import ContextTypes, ConversationHandler

from database import db, ensure_user, update_user, get_user
from keyboards import (
    onboard_welcome_kb, onboard_shift_type_kb, onboard_days_kb,
    onboard_section_done_kb, onboard_yes_no_kb, onboard_skip_kb,
    onboard_progress_text, main_menu_kb, RELATIONSHIP_TYPES,
)

logger = logging.getLogger(__name__)

# ── Awaiting-state constants ──
AWAITING_NAME           = "onboard_name"
AWAITING_PARTNER_NAME   = "onboard_partner_name"
AWAITING_BILL_NAME      = "onboard_bill_name"
AWAITING_BILL_AMOUNT    = "onboard_bill_amount"
AWAITING_CAR_DESC       = "onboard_car_desc"
AWAITING_CAR_DATE       = "onboard_car_date"
AWAITING_CRED_NAME      = "onboard_cred_name"
AWAITING_CRED_EXPIRY    = "onboard_cred_expiry"
AWAITING_MED_NAME       = "onboard_med_name"
AWAITING_CUSTOM_SHIFT   = "onboard_custom_shift"

# ── onboard_step → awaiting state mapping (for restart recovery) ──
STEP_TO_AWAITING = {
    "name":        AWAITING_NAME,
    "custom_shift": AWAITING_CUSTOM_SHIFT,
    "partner_name": AWAITING_PARTNER_NAME,
    "bill_name":   AWAITING_BILL_NAME,
    "bill_amount": AWAITING_BILL_AMOUNT,
    "car_desc":    AWAITING_CAR_DESC,
    "car_date":    AWAITING_CAR_DATE,
    "cred_name":   AWAITING_CRED_NAME,
    "cred_expiry": AWAITING_CRED_EXPIRY,
    "med_name":    AWAITING_MED_NAME,
}

# ─────────────────────────────────────────────────────────────────────────────
# INPUT VALIDATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _has_letter(text: str) -> bool:
    """Return True if text contains at least one Unicode letter character."""
    return bool(re.search(r'\w', text, re.UNICODE) and
                re.search(r'[^\W\d_]', text, re.UNICODE))


def validate_name(text: str, max_len: int = 100) -> tuple[bool, str]:
    """
    Validate a name/text field.
    Returns (ok, cleaned_or_error_message).
    When ok=True, cleaned_or_error_message is the cleaned name.
    When ok=False, it's a user-friendly error message.
    """
    cleaned = re.sub(r'  +', ' ', text.strip())
    if not cleaned:
        return False, "Hmm, that doesn't look like a name. Try typing just your name or nickname."
    if len(cleaned) > max_len:
        return False, f"That's a bit long — keep it under {max_len} characters."
    if not _has_letter(cleaned):
        return False, "Hmm, that doesn't look like a name. Try typing just your name or nickname."
    return True, cleaned


def validate_display_name(text: str) -> tuple[bool, str]:
    """
    Like validate_name but with extra restrictions for the display name:
    - Max 50 chars
    - Reject pure numbers
    """
    ok, result = validate_name(text, max_len=50)
    if not ok:
        return False, result
    # Reject names that are just numbers
    if re.match(r'^\d+$', result):
        return False, "Hmm, that doesn't look like a name. Try typing just your name or nickname."
    return True, result


def validate_bill_amount(text: str) -> tuple[bool, float | None, str]:
    """
    Validate a bill amount.
    Returns (ok, amount_or_None, error_message).
    amount_or_None is None for skip-words, float otherwise.
    error_message is empty string when ok=True.
    """
    cleaned = text.strip().lower()
    # Skip words → NULL amount
    if cleaned in ("skip", "idk", "?", "no", "not sure", "dunno", ""):
        return True, None, ""
    # Strip currency symbols / commas / spaces
    numeric_str = re.sub(r'[\$,\s]', '', text.strip())
    try:
        amount = float(numeric_str)
    except ValueError:
        return False, None, (
            "I didn't catch that. Type the dollar amount (like '150' or '$1,500'), "
            "or 'skip' if you're not sure."
        )
    if amount < 0:
        return False, None, "Bills can't be negative — just enter the amount you owe."
    if amount > 1_000_000:
        return False, None, "That seems really high. Double check and try again, or type 'skip'."
    return True, amount, ""


def validate_shift_desc(text: str) -> tuple[bool, str]:
    """
    Validate a custom shift description.
    Returns (ok, cleaned_or_error).
    """
    cleaned = text.strip()
    if not cleaned:
        return False, "Type your shift hours — something like '3p-11p' or '8a-4p'."
    if len(cleaned) > 50:
        return False, "Keep the shift description under 50 characters."
    return True, cleaned


def parse_date_loosely(text: str) -> tuple[bool, str, str]:
    """
    Enhanced date parser.
    Returns (ok, iso_date_str, error_message).
    error_message is empty when ok=True.
    """
    original = text.strip()
    text = original

    # Strip ordinal suffixes first
    text = re.sub(r'(\d+)(st|nd|rd|th)\b', r'\1', text, flags=re.IGNORECASE)

    today = date.today()

    # ── Relative words ────────────────────────────────────────
    lower = text.strip().lower()

    if lower == "tomorrow":
        return True, (today + timedelta(days=1)).isoformat(), ""

    if lower in ("next week", "in a week"):
        return True, (today + timedelta(weeks=1)).isoformat(), ""

    if lower in ("next month", "in a month"):
        d = today.replace(day=1)
        # advance month
        if d.month == 12:
            d = d.replace(year=d.year + 1, month=1)
        else:
            d = d.replace(month=d.month + 1)
        return True, d.isoformat(), ""

    if lower in ("next year", "in a year"):
        return True, today.replace(year=today.year + 1).isoformat(), ""

    # "in N weeks" / "in N months" / "in N days"
    m = re.match(r'in\s+(\d+)\s+(day|days|week|weeks|month|months|year|years)', lower)
    if m:
        n = int(m.group(1))
        unit = m.group(2).rstrip('s')
        if unit == "day":
            result = today + timedelta(days=n)
        elif unit == "week":
            result = today + timedelta(weeks=n)
        elif unit == "month":
            # approximate: add months
            month = today.month + n
            year = today.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            try:
                result = today.replace(year=year, month=month)
            except ValueError:
                result = today.replace(year=year, month=month, day=1)
        elif unit == "year":
            result = today.replace(year=today.year + n)
        return True, result.isoformat(), ""

    # ── ISO format ─────────────────────────────────────────────
    try:
        parsed = datetime.fromisoformat(text.strip())
        return True, parsed.strftime("%Y-%m-%d"), ""
    except ValueError:
        pass

    # ── "Month [Day[,]] Year" and variations ──────────────────
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    text_lower = text.lower()
    for mname, mnum in months.items():
        if mname in text_lower:
            year_match = re.search(r"20\d{2}", text)
            year = int(year_match.group()) if year_match else today.year
            # Find day (but not the year digits)
            text_no_year = text.replace(str(year), "") if year_match else text
            day_match = re.search(r"\b(\d{1,2})\b", text_no_year)
            day = int(day_match.group()) if day_match else 1
            try:
                result = date(year, mnum, day)
            except ValueError:
                result = date(year, mnum, 1)
            return True, result.isoformat(), ""

    # ── Could not parse ────────────────────────────────────────
    return (
        False, "",
        "I couldn't figure out that date. Try something like 'May 2026' or '2026-06-15', "
        "or 'in 6 months'."
    )


def validate_date(text: str, allow_past: bool = False) -> tuple[bool, str, str]:
    """
    Parse and validate a date.
    Returns (ok, iso_str, error_message).
    Rejects past dates and dates > 10 years out unless allow_past=True.
    """
    ok, iso_str, err = parse_date_loosely(text)
    if not ok:
        return False, "", err

    today = date.today()
    parsed = date.fromisoformat(iso_str)

    if not allow_past and parsed < today:
        return False, "", "That date already passed. When is it actually due?"

    if parsed > today.replace(year=today.year + 10):
        return False, "", (
            "That's pretty far out — are you sure? Type it again or try a closer date."
        )

    return True, iso_str, ""


# ─────────────────────────────────────────────────────────────────────────────
# DUPLICATE DETECTION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _check_duplicate(chat_id: int, table: str, name_col: str, name: str) -> bool:
    """Return True if a record with matching name (case-insensitive) already exists."""
    with db() as conn:
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE chat_id = ? AND LOWER({name_col}) = LOWER(?)",
            (chat_id, name),
        ).fetchone()
    return row is not None


# ─────────────────────────────────────────────────────────────────────────────
# ONBOARDING KEYBOARD HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _onboard_partner_type_kb(partner_id: int):
    """Relationship-type picker with onboard:partner_type callback pattern."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for key, (emoji, label) in RELATIONSHIP_TYPES.items():
        rows.append([InlineKeyboardButton(
            f"{emoji} {label}",
            callback_data=f"onboard:partner_type:{key}",
        )])
    return InlineKeyboardMarkup(rows)


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULE DISPLAY HELPER
# ─────────────────────────────────────────────────────────────────────────────

# Sun-Sat display order and names (Python weekday: Mon=0 … Sun=6)
_DISPLAY_ORDER = [6, 0, 1, 2, 3, 4, 5]  # Sun first
_DAY_ABBR = {6: "Sun", 0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat"}


def _days_to_str(day_list: list[int]) -> str:
    """Convert a list of weekday ints to comma-separated names in Sun-Sat order."""
    day_set = set(day_list)
    return ", ".join(_DAY_ABBR[d] for d in _DISPLAY_ORDER if d in day_set)


def _format_weeks_summary(weeks: list[list[int]]) -> str:
    """Format a list of week day-lists into a readable summary."""
    if not weeks:
        return "(no days saved)"
    lines = []
    for i, week in enumerate(weeks, 1):
        lines.append(f"  Week {i}: {_days_to_str(week)}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# START COMMAND
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# BACK-NAVIGATION HELPER
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_back(query: CallbackQuery, chat_id: int,
                       target: str, context) -> bool:
    """
    Handle onboard:back:<target> navigation.
    Returns True if handled, False if unknown target.
    """
    if target == "name":
        # Re-ask for name
        update_user(chat_id, onboard_step="name")
        context.user_data["awaiting"] = AWAITING_NAME
        await query.edit_message_text(
            f"{onboard_progress_text('name')}\n\n"
            "What should I call you?\n\n"
            "(Just type your name or nickname)"
        )
        return True

    if target == "shift_type":
        # Clear all schedule-related keys so re-entering starts fresh
        user = get_user(chat_id)
        ob_data = json.loads(user["onboard_data"] or "{}") if user else {}
        for key in ("week1_days", "week2_days", "weeks", "selected_days", "shift_type"):
            ob_data.pop(key, None)
        update_user(chat_id, onboard_step="shift_type", onboard_data=json.dumps(ob_data))
        context.user_data["awaiting"] = None
        display = user["display_name"] or "you" if user else "you"
        await query.edit_message_text(
            f"{onboard_progress_text('shift_type')}\n\n"
            f"OK {display}, what kind of shifts do you work?",
            reply_markup=onboard_shift_type_kb(),
        )
        return True

    if target == "schedule_result":
        # Re-show partners_intro (after schedule was saved)
        update_user(chat_id, onboard_step="partners_intro")
        context.user_data["awaiting"] = None
        await query.edit_message_text(
            f"{onboard_progress_text('partners_intro')}\n\n"
            "Want to add any partners or important people?\n"
            "I'll track birthdays, anniversaries, and help you schedule dates.\n\n"
            "You can always add more later.",
            reply_markup=onboard_yes_no_kb("onboard:add_partners",
                                           back_section="schedule_result"),
        )
        return True

    if target == "partners":
        # Back from bills → re-ask partners
        update_user(chat_id, onboard_step="partners_intro")
        context.user_data["awaiting"] = None
        await query.edit_message_text(
            f"{onboard_progress_text('partners_intro')}\n\n"
            "Want to add any partners or important people?\n"
            "I'll track birthdays, anniversaries, and help you schedule dates.\n\n"
            "You can always add more later.",
            reply_markup=onboard_yes_no_kb("onboard:add_partners",
                                           back_section="schedule_result"),
        )
        return True

    if target == "bills":
        # Back from car → re-ask bills
        update_user(chat_id, onboard_step="bills_intro")
        context.user_data["awaiting"] = None
        await query.edit_message_text(
            f"{onboard_progress_text('bills_intro')}\n\n"
            "Want to add your bills now?\n"
            "I'll remind you on payday and nag until they're paid.\n\n"
            "You can always add more later.",
            reply_markup=onboard_yes_no_kb("onboard:add_bills",
                                           back_section="partners"),
        )
        return True

    if target == "car":
        # Back from creds → re-ask car
        update_user(chat_id, onboard_step="car_intro")
        context.user_data["awaiting"] = None
        await query.edit_message_text(
            f"{onboard_progress_text('car_intro')}\n\n"
            "Got any car maintenance to track?\n"
            "(Oil changes, inspections, registration, etc.)",
            reply_markup=onboard_yes_no_kb("onboard:add_car",
                                           back_section="bills"),
        )
        return True

    if target == "creds":
        # Back from meds → re-ask creds
        update_user(chat_id, onboard_step="creds_intro")
        context.user_data["awaiting"] = None
        await query.edit_message_text(
            f"{onboard_progress_text('creds_intro')}\n\n"
            "Any professional licenses or certifications to track?\n"
            "(License numbers, expiry dates, CEU requirements)",
            reply_markup=onboard_yes_no_kb("onboard:add_creds",
                                           back_section="car"),
        )
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CALLBACK HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def onboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all onboard:* callbacks."""
    query = update.callback_query
    # NOTE: Do NOT call query.answer() here — button_router already does it
    # and wraps it in try/except to handle stale queries safely.
    chat_id = query.message.chat_id
    data = query.data  # e.g. "onboard:start", "onboard:shift:12p-12a"
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
        await _dispatch_onboard_action(query, chat_id, action, parts, context)
    except Exception:
        logger.error(
            f"Error in onboard_callback (action={action}, chat={chat_id}):\n"
            + traceback.format_exc()
        )
        try:
            await query.message.reply_text(
                "Something went wrong during setup. Let's try that step again."
            )
            # Re-show the current step
            user = get_user(chat_id)
            step = user["onboard_step"] if user else None
            if step:
                await _reshown_step(query, chat_id, step, context)
        except Exception:
            pass


async def _reshown_step(query, chat_id: int, step: str, context):
    """Re-display the prompt for the current onboard_step after an error."""
    if step == "name":
        context.user_data["awaiting"] = AWAITING_NAME
        await query.message.reply_text(
            f"{onboard_progress_text('name')}\n\nWhat should I call you?\n(Just type your name or nickname)"
        )
    elif step == "shift_type":
        await query.message.reply_text(
            f"{onboard_progress_text('shift_type')}\n\nWhat kind of shifts do you work?",
            reply_markup=onboard_shift_type_kb(),
        )
    elif step in ("shift_days", "partners_intro", "bills_intro",
                  "car_intro", "creds_intro", "meds_intro"):
        await query.message.reply_text(
            "Use the buttons to continue onboarding, or tap /start to restart."
        )


async def _dispatch_onboard_action(query: CallbackQuery, chat_id: int,
                                   action: str, parts: list, context):
    """All onboard callback logic, wrapped by onboard_callback's try/except."""
    user = get_user(chat_id)
    ob_data = json.loads(user["onboard_data"] or "{}") if user else {}

    # ── Back navigation ──────────────────────────────────────
    if action == "back":
        target = parts[2] if len(parts) > 2 else ""
        await _handle_back(query, chat_id, target, context)
        return

    # ── Skip individual item (used when user changes mind mid-entry) ─────────
    if action == "skip_item":
        # Figure out what we were entering and bail back to the "another?" prompt
        awaiting = context.user_data.get("awaiting")
        if awaiting == AWAITING_PARTNER_NAME:
            context.user_data["awaiting"] = None
            update_user(chat_id, onboard_step="bills_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('bills_intro')}\n\n"
                "No problem. Next: bills and money.",
                reply_markup=onboard_section_done_kb("bills_intro", back_section="partners"),
            )
        elif awaiting == AWAITING_BILL_NAME:
            context.user_data["awaiting"] = None
            update_user(chat_id, onboard_step="car_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('car_intro')}\n\n"
                "Skipped. Next: car and vehicle stuff.",
                reply_markup=onboard_section_done_kb("car_intro", back_section="bills"),
            )
        elif awaiting == AWAITING_CAR_DESC:
            context.user_data["awaiting"] = None
            update_user(chat_id, onboard_step="creds_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('creds_intro')}\n\n"
                "Skipped. Next: professional credentials.",
                reply_markup=onboard_section_done_kb("creds_intro", back_section="car"),
            )
        elif awaiting == AWAITING_CRED_NAME:
            context.user_data["awaiting"] = None
            update_user(chat_id, onboard_step="meds_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('meds_intro')}\n\n"
                "Skipped. Last one: medications.",
                reply_markup=onboard_section_done_kb("meds_intro", back_section="creds"),
            )
        elif awaiting == AWAITING_MED_NAME:
            context.user_data["awaiting"] = None
            await _finish_onboarding(query, chat_id)
        else:
            # Unknown skip context — just clear and continue
            context.user_data["awaiting"] = None
            await query.edit_message_text(
                "Skipped. Tap /menu to continue or use the buttons.",
                reply_markup=main_menu_kb(),
            )
        return

    # ── Welcome ──────────────────────────────────────────────
    if action == "start":
        # Reset onboarded flag so the full flow runs clean
        update_user(chat_id, onboarded=0, onboard_step="name", onboard_data=json.dumps({}))
        context.user_data["awaiting"] = AWAITING_NAME
        logger.info(f"Onboarding started for {chat_id}, awaiting={AWAITING_NAME}")
        await query.edit_message_text(
            f"{onboard_progress_text('name')}\n\n"
            "First — what should I call you?\n\n"
            "(Just type your name or nickname)"
        )
        return

    if action == "skip":
        update_user(chat_id, onboarded=1)
        await query.edit_message_text(
            "No problem — you can set everything up later from the menu.\n\n"
            "Tap /menu anytime.",
            reply_markup=main_menu_kb(),
        )
        return

    # ── Shift Type ───────────────────────────────────────────
    if action == "shift":
        shift_type = parts[2] if len(parts) > 2 else "custom"
        ob_data["shift_type"] = shift_type
        update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="shift_days")

        if shift_type == "custom":
            update_user(chat_id, onboard_step="custom_shift")
            context.user_data["awaiting"] = AWAITING_CUSTOM_SHIFT
            await query.edit_message_text(
                f"{onboard_progress_text('shift_type')}\n\n"
                "What are your shift hours? (e.g. '3p-11p')\nJust type it out.",
                reply_markup=onboard_skip_kb(),
            )
        else:
            context.user_data["awaiting"] = None
            await query.edit_message_text(
                f"{onboard_progress_text('shift_days')}\n\n"
                "Which days do you usually work?\nTap to select, then hit Done.\n\n"
                "(If you rotate, pick your Week 1 days first)",
                reply_markup=onboard_days_kb([]),
            )
        return

    # ── Day Selection (multi-select) ─────────────────────────
    if action == "day":
        day_num = int(parts[2])
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
        selected = ob_data.get("selected_days", [])

        # Validate: at least 1 day
        if not selected:
            await query.answer(
                "You need to pick at least one day — tap the days you work.",
                show_alert=True,
            )
            return

        # Save current week into the weeks list
        weeks = ob_data.get("weeks", [])
        weeks.append(sorted(selected))
        ob_data["weeks"] = weeks
        ob_data["selected_days"] = []
        update_user(chat_id, onboard_data=json.dumps(ob_data))

        week_num = len(weeks)
        all_7_note = " Every day? Respect. 💪" if len(selected) == 7 else ""
        week_summary = _format_weeks_summary(weeks)
        next_week_num = week_num + 1

        await query.edit_message_text(
            f"{week_summary}{all_7_note}\n\n"
            f"Add Week {next_week_num} to the rotation?",
            reply_markup=onboard_yes_no_kb("onboard:add_week",
                                           back_section="shift_type"),
        )
        return

    if action == "add_week":
        answer = parts[2] if len(parts) > 2 else "no"

        if answer == "yes":
            ob_data["selected_days"] = []
            update_user(chat_id, onboard_data=json.dumps(ob_data))
            week_num = len(ob_data.get("weeks", [])) + 1
            await query.edit_message_text(
                f"{onboard_progress_text('shift_days')}\n\n"
                f"Pick your Week {week_num} days:",
                reply_markup=onboard_days_kb([]),
            )
        else:
            # Done — compile and save
            weeks = ob_data.get("weeks", [])
            if not weeks:
                # Fallback: shouldn't happen but guard
                await query.answer("No days saved. Please pick your days.", show_alert=True)
                return

            # Back-compat: always store week1_days + week2_days for other modules
            ob_data["week1_days"] = weeks[0]
            ob_data["week2_days"] = weeks[1] if len(weeks) > 1 else weeks[0]
            ob_data.pop("selected_days", None)
            update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="partners_intro")

            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO shifts (chat_id, shift_type, week1_days, week2_days) "
                    "VALUES (?, ?, ?, ?)",
                    (chat_id, ob_data.get("shift_type", "custom"),
                     json.dumps(ob_data["week1_days"]), json.dumps(ob_data["week2_days"])),
                )

            week_summary = _format_weeks_summary(weeks)
            await query.edit_message_text(
                f"{onboard_progress_text('partners_intro')}\n\n"
                f"Schedule saved.\n{week_summary}\n\n"
                "Next up: people and relationships.",
                reply_markup=onboard_section_done_kb("partners_intro",
                                                     back_section="shift_type"),
            )
        return

    # ── Partners Intro ───────────────────────────────────────
    if action == "partners_intro":
        update_user(chat_id, onboard_step="partners_intro")
        await query.edit_message_text(
            f"{onboard_progress_text('partners_intro')}\n\n"
            "Want to add any partners or important people?\n"
            "I'll track birthdays, anniversaries, and help you schedule dates.\n\n"
            "You can always add more later.",
            reply_markup=onboard_yes_no_kb("onboard:add_partners",
                                           back_section="schedule_result"),
        )
        return

    if action == "add_partners":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="partner_name")
            context.user_data["awaiting"] = AWAITING_PARTNER_NAME
            await query.edit_message_text(
                f"{onboard_progress_text('partners_intro')}\n\n"
                "Type their name (or nickname):",
                reply_markup=onboard_skip_kb(),
            )
        else:
            update_user(chat_id, onboard_step="bills_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('bills_intro')}\n\n"
                "No worries. Next: bills and money.",
                reply_markup=onboard_section_done_kb("bills_intro",
                                                     back_section="partners"),
            )
        return

    if action == "partner_type":
        # onboard:partner_type:{type_key}
        type_key = parts[2] if len(parts) > 2 else "important"
        partner_id = ob_data.get("pending_partner_id")
        if partner_id and type_key in RELATIONSHIP_TYPES:
            with db() as conn:
                conn.execute(
                    "UPDATE partners SET relationship_type = ? WHERE id = ? AND chat_id = ?",
                    (type_key, partner_id, chat_id),
                )
        ob_data.pop("pending_partner_id", None)
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        emoji, label = RELATIONSHIP_TYPES.get(type_key, ("💜", "Person"))
        await query.edit_message_text(
            f"{emoji} Got it — saved as {label}.\n\nAnother person?",
            reply_markup=onboard_yes_no_kb("onboard:another_partner"),
        )
        return

    if action == "another_partner":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="partner_name")
            context.user_data["awaiting"] = AWAITING_PARTNER_NAME
            await query.edit_message_text(
                f"{onboard_progress_text('partners_intro')}\n\n"
                "Type their name:",
                reply_markup=onboard_skip_kb(),
            )
        else:
            update_user(chat_id, onboard_step="bills_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('bills_intro')}\n\n"
                "People saved. Next: bills and money.",
                reply_markup=onboard_section_done_kb("bills_intro",
                                                     back_section="partners"),
            )
        return

    # ── Bills Intro ──────────────────────────────────────────
    if action == "bills_intro":
        update_user(chat_id, onboard_step="bills_intro")
        await query.edit_message_text(
            f"{onboard_progress_text('bills_intro')}\n\n"
            "Want to add your bills now?\n"
            "I'll remind you on payday and nag until they're paid.\n\n"
            "You can always add more later.",
            reply_markup=onboard_yes_no_kb("onboard:add_bills",
                                           back_section="partners"),
        )
        return

    if action == "add_bills":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="bill_name")
            context.user_data["awaiting"] = AWAITING_BILL_NAME
            await query.edit_message_text(
                f"{onboard_progress_text('bills_intro')}\n\n"
                "Bill name? (e.g. 'Mortgage', 'PECO')",
                reply_markup=onboard_skip_kb(),
            )
        else:
            update_user(chat_id, onboard_step="car_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('car_intro')}\n\n"
                "Alright. Next: car and vehicle stuff.",
                reply_markup=onboard_section_done_kb("car_intro", back_section="bills"),
            )
        return

    if action == "another_bill":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="bill_name")
            context.user_data["awaiting"] = AWAITING_BILL_NAME
            await query.edit_message_text(
                f"{onboard_progress_text('bills_intro')}\n\nBill name?",
                reply_markup=onboard_skip_kb(),
            )
        else:
            update_user(chat_id, onboard_step="car_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('car_intro')}\n\nBills saved. Next: car stuff.",
                reply_markup=onboard_section_done_kb("car_intro", back_section="bills"),
            )
        return

    # ── Car Intro ────────────────────────────────────────────
    if action == "car_intro":
        update_user(chat_id, onboard_step="car_intro")
        await query.edit_message_text(
            f"{onboard_progress_text('car_intro')}\n\n"
            "Got any car maintenance to track?\n"
            "(Oil changes, inspections, registration, etc.)",
            reply_markup=onboard_yes_no_kb("onboard:add_car", back_section="bills"),
        )
        return

    if action == "add_car":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="car_desc")
            context.user_data["awaiting"] = AWAITING_CAR_DESC
            await query.edit_message_text(
                f"{onboard_progress_text('car_intro')}\n\n"
                "What's the item? (e.g. 'Oil change', 'State inspection')",
                reply_markup=onboard_skip_kb(),
            )
        else:
            update_user(chat_id, onboard_step="creds_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('creds_intro')}\n\n"
                "No problem. Next: professional credentials.",
                reply_markup=onboard_section_done_kb("creds_intro", back_section="car"),
            )
        return

    if action == "another_car":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="car_desc")
            context.user_data["awaiting"] = AWAITING_CAR_DESC
            await query.edit_message_text(
                f"{onboard_progress_text('car_intro')}\n\nWhat's the item?",
                reply_markup=onboard_skip_kb(),
            )
        else:
            update_user(chat_id, onboard_step="creds_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('creds_intro')}\n\nCar items saved. Next: credentials.",
                reply_markup=onboard_section_done_kb("creds_intro", back_section="car"),
            )
        return

    # ── Credentials Intro ────────────────────────────────────
    if action == "creds_intro":
        update_user(chat_id, onboard_step="creds_intro")
        await query.edit_message_text(
            f"{onboard_progress_text('creds_intro')}\n\n"
            "Any professional licenses or certifications to track?\n"
            "(License numbers, expiry dates, CEU requirements)",
            reply_markup=onboard_yes_no_kb("onboard:add_creds", back_section="car"),
        )
        return

    if action == "add_creds":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="cred_name")
            context.user_data["awaiting"] = AWAITING_CRED_NAME
            await query.edit_message_text(
                f"{onboard_progress_text('creds_intro')}\n\n"
                "Credential name? (e.g. 'RRT License', 'BLS', 'ACLS')",
                reply_markup=onboard_skip_kb(),
            )
        else:
            update_user(chat_id, onboard_step="meds_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('meds_intro')}\n\n"
                "Got it. Last one: medications.",
                reply_markup=onboard_section_done_kb("meds_intro", back_section="creds"),
            )
        return

    if action == "another_cred":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="cred_name")
            context.user_data["awaiting"] = AWAITING_CRED_NAME
            await query.edit_message_text(
                f"{onboard_progress_text('creds_intro')}\n\nCredential name?",
                reply_markup=onboard_skip_kb(),
            )
        else:
            update_user(chat_id, onboard_step="meds_intro")
            await query.edit_message_text(
                f"{onboard_progress_text('meds_intro')}\n\n"
                "Credentials saved. Last one: medications.",
                reply_markup=onboard_section_done_kb("meds_intro", back_section="creds"),
            )
        return

    # ── Meds Intro ───────────────────────────────────────────
    if action == "meds_intro":
        update_user(chat_id, onboard_step="meds_intro")
        await query.edit_message_text(
            f"{onboard_progress_text('meds_intro')}\n\n"
            "Any daily medications to remind you about?\n"
            "I'll check in until you confirm you took them.",
            reply_markup=onboard_yes_no_kb("onboard:add_meds", back_section="creds"),
        )
        return

    if action == "add_meds":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="med_name")
            context.user_data["awaiting"] = AWAITING_MED_NAME
            await query.edit_message_text(
                f"{onboard_progress_text('meds_intro')}\n\nMedication name?",
                reply_markup=onboard_skip_kb(),
            )
        else:
            await _finish_onboarding(query, chat_id)
        return

    if action == "another_med":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="med_name")
            context.user_data["awaiting"] = AWAITING_MED_NAME
            await query.edit_message_text(
                f"{onboard_progress_text('meds_intro')}\n\nMedication name?",
                reply_markup=onboard_skip_kb(),
            )
        else:
            await _finish_onboarding(query, chat_id)
        return

    # ── Finish ───────────────────────────────────────────────
    if action == "finish":
        await _finish_onboarding(query, chat_id)
        return


# ─────────────────────────────────────────────────────────────────────────────
# FINISH ONBOARDING
# ─────────────────────────────────────────────────────────────────────────────

async def _finish_onboarding(query: CallbackQuery, chat_id: int):
    update_user(chat_id, onboarded=1, onboard_step=None)
    await query.edit_message_text(
        "You're all set. 🫡\n\n"
        "I'll start keeping track of everything.\n"
        "Tap /menu anytime — or I'll check in with you on schedule.\n\n"
        "You can always add or change things from the menu.",
        reply_markup=main_menu_kb(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEXT INPUT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_onboard_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handle text messages during onboarding.
    Uses DB onboard_step as source of truth to recover from bot restarts.
    Returns True if the message was consumed, False if it should pass through.
    """
    chat_id = update.effective_chat.id
    user = get_user(chat_id)

    if not user:
        return False

    awaiting = context.user_data.get("awaiting")
    onboard_step = user["onboard_step"] if user else None
    logger.info(f"[ONBOARD-TEXT] chat={chat_id} awaiting={awaiting} onboard_step={onboard_step} text='{update.message.text.strip()[:30]}'")

    if not awaiting or not str(awaiting).startswith("onboard"):
        # Not in an onboarding awaiting state in memory — check DB
        if onboard_step and onboard_step in STEP_TO_AWAITING:
            # Recover: restore the awaiting state from DB
            awaiting = STEP_TO_AWAITING[onboard_step]
            context.user_data["awaiting"] = awaiting
            logger.info(
                f"Recovered onboard awaiting from DB: step={onboard_step} → {awaiting} "
                f"(chat={chat_id})"
            )
        else:
            return False  # Not in onboarding

    if not str(awaiting).startswith("onboard"):
        return False

    text = update.message.text.strip()
    ob_data = json.loads(user["onboard_data"] or "{}")

    # ── Name ─────────────────────────────────────────────────
    if awaiting == AWAITING_NAME:
        ok, result = validate_display_name(text)
        if not ok:
            await update.message.reply_text(result)
            return True
        name = result
        update_user(chat_id, display_name=name, onboard_step="shift_type")
        ob_data["name"] = name
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        context.user_data["awaiting"] = None
        logger.info(f"[ONBOARD] Name='{name}' saved, sending shift_type keyboard (chat={chat_id})")
        try:
            msg = await update.message.reply_text(
                f"{onboard_progress_text('shift_type')}\n\n"
                f"Nice to meet you, {name}.\n\n"
                "What kind of shifts do you work?",
                reply_markup=onboard_shift_type_kb(),
            )
            logger.info(f"[ONBOARD] Shift keyboard sent OK, msg_id={msg.message_id} (chat={chat_id})")
        except Exception as e:
            logger.error(f"[ONBOARD] FAILED to send shift keyboard: {e} (chat={chat_id})")
            # Fallback: try sending without edit
            await update.message.reply_text(
                f"Nice to meet you, {name}. What kind of shifts do you work?",
                reply_markup=onboard_shift_type_kb(),
            )
        return True

    # ── Custom Shift ─────────────────────────────────────────
    if awaiting == AWAITING_CUSTOM_SHIFT:
        ok, result = validate_shift_desc(text)
        if not ok:
            await update.message.reply_text(result, reply_markup=onboard_skip_kb())
            return True
        ob_data["shift_type"] = result
        update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="shift_days")
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"{onboard_progress_text('shift_days')}\n\n"
            f"Got it: {result}\n\nWhich days do you usually work? Tap to select:",
            reply_markup=onboard_days_kb([]),
        )
        return True

    # ── Partner Name ─────────────────────────────────────────
    if awaiting == AWAITING_PARTNER_NAME:
        ok, result = validate_name(text)
        if not ok:
            await update.message.reply_text(result, reply_markup=onboard_skip_kb())
            return True
        name = result
        # Duplicate check
        if _check_duplicate(chat_id, "partners", "name", name):
            await update.message.reply_text(
                f"You already added {name}. Want to add someone else?",
                reply_markup=onboard_yes_no_kb("onboard:another_partner"),
            )
            context.user_data["awaiting"] = None
            return True
        with db() as conn:
            cursor = conn.execute(
                "INSERT INTO partners (chat_id, name) VALUES (?, ?)",
                (chat_id, name),
            )
            partner_id = cursor.lastrowid
        ob_data["pending_partner_id"] = partner_id
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        context.user_data["awaiting"] = None
        # Show relationship type picker before asking "another?"
        type_kb = _onboard_partner_type_kb(partner_id)
        await update.message.reply_text(
            f"Added {name} 💜\n\nWhat\'s their relationship to you?",
            reply_markup=type_kb,
        )
        return True

    # ── Bill Name ────────────────────────────────────────────
    if awaiting == AWAITING_BILL_NAME:
        ok, result = validate_name(text)
        if not ok:
            await update.message.reply_text(result, reply_markup=onboard_skip_kb())
            return True
        name = result
        # Duplicate check
        if _check_duplicate(chat_id, "bills", "name", name):
            await update.message.reply_text(
                f"You already added '{name}'. Want to add a different bill?",
                reply_markup=onboard_yes_no_kb("onboard:another_bill"),
            )
            context.user_data["awaiting"] = None
            return True
        ob_data["pending_bill_name"] = name
        update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="bill_amount")
        context.user_data["awaiting"] = AWAITING_BILL_AMOUNT
        await update.message.reply_text(
            f"How much is {name}? (Just the number, or type 'skip')"
        )
        return True

    # ── Bill Amount ──────────────────────────────────────────
    if awaiting == AWAITING_BILL_AMOUNT:
        ok, amount, err = validate_bill_amount(text)
        if not ok:
            await update.message.reply_text(err)
            return True
        bill_name = ob_data.pop("pending_bill_name", "Unknown")
        with db() as conn:
            conn.execute(
                "INSERT INTO bills (chat_id, name, amount) VALUES (?, ?, ?)",
                (chat_id, bill_name, amount),
            )
        update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="car_intro")
        context.user_data["awaiting"] = None
        amt_str = f" (${amount:,.0f})" if amount is not None else ""
        await update.message.reply_text(
            f"Added {bill_name}{amt_str} 💸\n\nAnother bill?",
            reply_markup=onboard_yes_no_kb("onboard:another_bill"),
        )
        return True

    # ── Car Description ──────────────────────────────────────
    if awaiting == AWAITING_CAR_DESC:
        ok, result = validate_name(text)
        if not ok:
            await update.message.reply_text(result, reply_markup=onboard_skip_kb())
            return True
        desc = result
        # Duplicate check
        if _check_duplicate(chat_id, "car_events", "description", desc):
            await update.message.reply_text(
                f"You already have '{desc}'. Want to add a different car item?",
                reply_markup=onboard_yes_no_kb("onboard:another_car"),
            )
            context.user_data["awaiting"] = None
            return True
        ob_data["pending_car_desc"] = desc
        update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="car_date")
        context.user_data["awaiting"] = AWAITING_CAR_DATE
        await update.message.reply_text(
            f"When is '{desc}' due? (e.g. '2026-05-18' or 'May 2026' or 'in 6 months')"
        )
        return True

    # ── Car Date ─────────────────────────────────────────────
    if awaiting == AWAITING_CAR_DATE:
        ok, iso_str, err = validate_date(text)
        if not ok:
            await update.message.reply_text(err)
            return True
        car_desc = ob_data.pop("pending_car_desc", "Car item")
        with db() as conn:
            conn.execute(
                "INSERT INTO car_events (chat_id, event_type, description, due_date) "
                "VALUES (?, ?, ?, ?)",
                (chat_id, "custom", car_desc, iso_str),
            )
        update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="creds_intro")
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"Added: {car_desc} — due {iso_str} 🚗\n\nAnother car item?",
            reply_markup=onboard_yes_no_kb("onboard:another_car"),
        )
        return True

    # ── Credential Name ──────────────────────────────────────
    if awaiting == AWAITING_CRED_NAME:
        ok, result = validate_name(text)
        if not ok:
            await update.message.reply_text(result, reply_markup=onboard_skip_kb())
            return True
        name = result
        # Duplicate check
        if _check_duplicate(chat_id, "credentials", "name", name):
            await update.message.reply_text(
                f"You already have '{name}'. Want to add a different credential?",
                reply_markup=onboard_yes_no_kb("onboard:another_cred"),
            )
            context.user_data["awaiting"] = None
            return True
        ob_data["pending_cred_name"] = name
        update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="cred_expiry")
        context.user_data["awaiting"] = AWAITING_CRED_EXPIRY
        await update.message.reply_text(
            f"When does '{name}' expire? (e.g. '2027-06-01' or 'June 2027')"
        )
        return True

    # ── Credential Expiry ────────────────────────────────────
    if awaiting == AWAITING_CRED_EXPIRY:
        # Credentials can expire in the future, allow past slightly (already expired = valid data)
        ok, iso_str, err = validate_date(text, allow_past=True)
        if not ok:
            await update.message.reply_text(err)
            return True
        cred_name = ob_data.pop("pending_cred_name", "Credential")
        with db() as conn:
            conn.execute(
                "INSERT INTO credentials (chat_id, name, expiry_date) VALUES (?, ?, ?)",
                (chat_id, cred_name, iso_str),
            )
        update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="meds_intro")
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"Added: {cred_name} — expires {iso_str} 🎓\n\nAnother credential?",
            reply_markup=onboard_yes_no_kb("onboard:another_cred"),
        )
        return True

    # ── Medication Name ──────────────────────────────────────
    if awaiting == AWAITING_MED_NAME:
        ok, result = validate_name(text)
        if not ok:
            await update.message.reply_text(result, reply_markup=onboard_skip_kb())
            return True
        name = result
        # Duplicate check
        if _check_duplicate(chat_id, "medications", "name", name):
            await update.message.reply_text(
                f"You already added '{name}'. Want to add a different medication?",
                reply_markup=onboard_yes_no_kb("onboard:another_med"),
            )
            context.user_data["awaiting"] = None
            return True
        with db() as conn:
            conn.execute(
                "INSERT INTO medications (chat_id, name) VALUES (?, ?)",
                (chat_id, name),
            )
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"Added: {name} 💊\n\nAnother medication?",
            reply_markup=onboard_yes_no_kb("onboard:another_med"),
        )
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY: keep _parse_date_loosely for any external callers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date_loosely(text: str) -> str:
    """Best-effort date parsing. Returns ISO date string or original text on failure."""
    ok, iso_str, _ = parse_date_loosely(text)
    if ok:
        return iso_str
    return text.strip()
