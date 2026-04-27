# Butler Bot
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
Butler Bot — main entry point.
Telegram personal assistant for shift workers.
Button-first, ADHD-friendly, aggressive reminders.
"""
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import time as dt_time

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from config import BOT_TOKEN, DAILY_DIGEST_HOUR, EVENING_CHECKIN_HOUR, WEEKLY_DIGEST_DAY, WEEKLY_DIGEST_HOUR
from database import init_db
from keyboards import main_menu_kb, settings_kb

# Module imports
from modules.onboarding import start_command, onboard_callback, handle_onboard_text
from modules.today import today_view
from modules.week_view import week_callback
from modules.bills import bills_callback, handle_bill_text
from modules.partners import partners_callback, handle_partner_text, partner_date_picker_callback
from modules.date_picker import datepick_callback
from modules.me_time import metime_callback
from modules.car import car_callback, handle_car_text, car_datepick_callback
from modules.credentials import creds_callback, handle_cred_text, cred_datepick_callback
from modules.meds import meds_callback, handle_med_text
from modules.notes import notes_callback, handle_note_text
from modules.appointments import appts_callback, handle_appt_text, appt_datepick_callback
from modules.settings_handlers import handle_settings_text, handle_settings_day_select
from modules.field_editor import handle_field_edit_text
from modules.scheduler import (
    daily_reset, afternoon_digest, evening_checkin,
    med_nag, bill_nag, weekly_digest, appointment_reminder_check,
    morning_heartbeat, evening_touch,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ── COMMAND HANDLERS (minimal — just /start and /menu) ──

BOT_VERSION = "2.7.5"
BUILD_DATE = "2026-04-08-v2"

def _week_emoji_row(days: list[int]) -> str:
    """Build a Sun-Sat emoji row for schedule display."""
    sun_sat = [6, 0, 1, 2, 3, 4, 5]
    return "  ".join("🏥" if d in days else "🏠" for d in sun_sat)

async def _version_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug: show which version is actually running."""
    await update.message.reply_text(f"🔧 Butler Bot {BOT_VERSION} ({BUILD_DATE})\nDeploy: nixpacks")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The /menu command — main entry point."""
    from database import ensure_user, get_user, update_user, db
    chat_id = update.effective_chat.id
    name = update.effective_user.first_name
    is_onboarded = ensure_user(chat_id, name)

    if not is_onboarded:
        # Check if they actually have data — if so, just unlock the menu.
        # This covers the case where someone hit Menu mid-onboarding.
        with db() as conn:
            has_data = any([
                conn.execute("SELECT 1 FROM partners WHERE chat_id = ? LIMIT 1", (chat_id,)).fetchone(),
                conn.execute("SELECT 1 FROM bills WHERE chat_id = ? LIMIT 1", (chat_id,)).fetchone(),
                conn.execute("SELECT 1 FROM medications WHERE chat_id = ? LIMIT 1", (chat_id,)).fetchone(),
                conn.execute("SELECT 1 FROM credentials WHERE chat_id = ? LIMIT 1", (chat_id,)).fetchone(),
            ])
        if has_data:
            # They have real data. Mark them onboarded and show the menu.
            update_user(chat_id, onboarded=1, onboard_step=None)
            is_onboarded = True
        else:
            await start_command(update, context)
            return

    # Clear ALL state — memory and DB onboard_step
    _clear_input_state(context)
    update_user(chat_id, onboard_step=None)
    user = get_user(chat_id)
    display = user["display_name"] if user and user["display_name"] else None
    greeting = f"What do you need, {display}? 🫡" if display else "What do you need? 🫡"
    await update.message.reply_text(greeting, reply_markup=main_menu_kb())


# ── CALLBACK ROUTER — all button presses go here ──

def _clear_input_state(context: ContextTypes.DEFAULT_TYPE):
    """Clear ALL text-input state from context.user_data.

    Called whenever a button is pressed so stale awaiting flags
    never block future flows.  Each module stores temp keys
    during multi-step creation; we wipe them all here.
    """
    # The master "awaiting" flag that text_router checks
    context.user_data.pop("awaiting", None)

    # ── Appointment temp keys ────────────────────────
    for k in ("appt_title", "appt_date", "appt_time", "appt_notes",
              "appt_category", "appt_priority", "appt_reminder_level"):
        context.user_data.pop(k, None)

    # ── Bill temp keys ───────────────────────────────
    for k in ("new_bill_name", "new_bill_amount", "new_bill_name_final",
              "edit_bill_id", "edit_bill_field"):
        context.user_data.pop(k, None)

    # ── Partner temp keys ────────────────────────────
    for k in ("pending_date_type", "pending_date_partner",
              "edit_partner_id", "new_partner_type", "new_partner_freq"):
        context.user_data.pop(k, None)

    # ── Car temp keys ────────────────────────────────
    for k in ("new_car_type", "new_car_desc", "edit_car_id"):
        context.user_data.pop(k, None)

    # ── Credential temp keys ─────────────────────────
    for k in ("new_cred_name", "edit_cred_id", "edit_cred_field"):
        context.user_data.pop(k, None)

    # ── Med temp keys ────────────────────────────────
    for k in ("new_med_name", "edit_med_id"):
        context.user_data.pop(k, None)

    # ── Note temp keys ───────────────────────────────
    for k in ("note_category", "note_ref_id"):
        context.user_data.pop(k, None)

    # ── Field editor temp keys ───────────────────────
    for k in ("field_edit_module", "field_edit_id", "field_edit_field"):
        context.user_data.pop(k, None)

    # ── Settings temp keys ───────────────────────────
    for k in ("settings_editing", "settings_selected_days"):
        context.user_data.pop(k, None)


async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all inline keyboard button presses by prefix."""
    query = update.callback_query
    data = query.data
    logger.info(f"Button pressed: {data} (user: {query.from_user.id})")

    # Always answer the callback first to stop the loading spinner.
    # Wrap in try/except because stale queries (tapped during downtime) will fail.
    try:
        await query.answer()
    except Exception:
        pass

    # ── CRITICAL: Clear any stale text-input state ────────────
    # If user taps a button, they're navigating — any pending
    # "awaiting" flag from a prior flow is stale and must die.
    # Without this, a leftover awaiting flag causes the text_router
    # to swallow subsequent inputs or blocks button flows.
    #
    # Exception: settings day-picker reuses onboard:day callbacks
    # while settings_editing is active — don't clear in that case.
    # Also preserve state for in-progress appointment creation steps
    # that use buttons mid-flow (category, priority, skip).
    # Only preserve state for settings day-picker (onboard:day:*) and appointment
    # mid-flow buttons. Everything else clears stale state.
    _is_settings_day_pick = (
        context.user_data.get("settings_editing")
        and data.startswith("onboard:day:")  # ONLY day toggles, not onboard:start etc.
    )
    _is_appt_midflow = data.startswith("appts:") and any(
        data.startswith(f"appts:{a}")
        for a in ("category:", "skip_time", "skip_notes",
                   "priority_ok", "priority_none",
                   "priority_up", "priority_down")
    )
    if not _is_settings_day_pick and not _is_appt_midflow:
        _clear_input_state(context)

    prefix = data.split(":")[0]

    # Settings day-picker reuses onboard:day and onboard:days_done callbacks
    if context.user_data.get("settings_editing") and data.startswith("onboard:day"):
        await handle_settings_day_select(update, context)
        return

    # Handle noop buttons (informational headers in grids)
    if data == "noop":
        return

    # Guard: if the user is mid-onboarding, block menu module buttons
    # that would start a competing flow and cause visual confusion.
    # Only onboard:*, menu:main, settings:*, and today:* are allowed through.
    if prefix not in ("onboard", "menu", "settings", "today", "noop", "alter"):
        from database import get_user as _gu
        _u = _gu(query.message.chat_id)
        if _u and _u.get("onboard_step") and _u.get("onboarded") == 0:
            # User is actively in onboarding — redirect gently
            await query.edit_message_text(
                "Finish setting up first — then everything else unlocks. "
                "Tap Next or Back to continue."
            )
            return

    routers = {
        "menu":      handle_menu,
        "today":     today_view,
        "week":      week_callback,
        "bills":     bills_callback,
        "partners":  partners_callback,
        "car":       car_callback,
        "creds":     creds_callback,
        "meds":      meds_callback,
        "notes":     notes_callback,
        "appts":     appts_callback,
        "capture":   handle_capture,
        "settings":  handle_settings,
        "onboard":   onboard_callback,
        "datepick":  datepick_callback,
        "pdatepick": partner_date_picker_callback,
        "alter":     handle_alter_schedule,
        "metime":    metime_callback,
        "cardp":     car_datepick_callback,
        "creddp":    cred_datepick_callback,
        "apptdp":    appt_datepick_callback,
    }

    handler = routers.get(prefix)
    if handler:
        try:
            await handler(update, context)
        except Exception as e:
            logger.error(f"Error in {prefix} handler: {e}", exc_info=True)
            try:
                # Show the actual error briefly to help debug
                err_short = str(e)[:100]
                await query.message.reply_text(
                    f"Something went wrong: {err_short}\n\nTap /menu to try again."
                )
            except Exception:
                pass
    else:
        logger.warning(f"Unknown callback prefix: {prefix} (data: {data})")
        try:
            await query.message.reply_text("Unknown action. Tap /menu.")
        except Exception:
            pass


async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu:main callback."""
    import random
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    # Wipe ALL input state — both memory AND DB onboard_step
    # This prevents onboarding bleed-over when user exits mid-flow
    _clear_input_state(context)
    from database import update_user, get_user
    update_user(chat_id, onboard_step=None)
    greeting = random.choice(["What do you need? 🫡", "I'm here. What's up?", "Ready when you are."])
    await query.edit_message_text(greeting, reply_markup=main_menu_kb())


async def handle_alter_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle alter:* callbacks — quick schedule changes from Today/Week view."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "start"

    if action == "start":
        from keyboards import alter_schedule_kb
        await query.edit_message_text(
            "📅 ALTER SCHEDULE\n\n"
            "Pick a day to change, or edit your full rotation.",
            reply_markup=alter_schedule_kb(),
        )

    elif action == "day":
        # alter:day:{iso_date} — user picked a specific day
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from datetime import date as _date
        day_str = parts[2] if len(parts) > 2 else ""
        try:
            target = _date.fromisoformat(day_str)
        except ValueError:
            await query.edit_message_text("Invalid date. Tap /menu.")
            return
        weekday_name = target.strftime("%A %b %d")
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🏥 Working", callback_data=f"alter:setday:{day_str}:on"),
                InlineKeyboardButton("🏠 Off", callback_data=f"alter:setday:{day_str}:off"),
            ],
            [InlineKeyboardButton("⬅️ Back", callback_data="alter:start")],
        ])
        await query.edit_message_text(
            f"Is {weekday_name} a work day?",
            reply_markup=kb,
        )

    elif action == "setday":
        # alter:setday:{iso_date}:{on|off} — ask week-only or permanent
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from datetime import date as _date
        day_str = parts[2] if len(parts) > 2 else ""
        status = parts[3] if len(parts) > 3 else "off"
        try:
            target = _date.fromisoformat(day_str)
        except ValueError:
            await query.edit_message_text("Invalid date. Tap /menu.")
            return
        status_label = "🏥 Working" if status == "on" else "🏠 Off"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Just this week", callback_data=f"alter:scope:{day_str}:{status}:week")],
            [InlineKeyboardButton("🔄 Change rotation", callback_data=f"alter:scope:{day_str}:{status}:perm")],
            [InlineKeyboardButton("⬅️ Back", callback_data=f"alter:day:{day_str}")],
        ])
        await query.edit_message_text(
            f"{status_label} on {target.strftime('%A %b %d')}\n\n"
            "Just this week, or change your rotation permanently?",
            reply_markup=kb,
        )

    elif action == "scope":
        # alter:scope:{iso_date}:{on|off}:{week|perm}
        from database import db
        from datetime import date as _date
        import json as _json
        day_str = parts[2] if len(parts) > 2 else ""
        status = parts[3] if len(parts) > 3 else "off"
        scope = parts[4] if len(parts) > 4 else "week"
        try:
            target = _date.fromisoformat(day_str)
        except ValueError:
            await query.edit_message_text("Invalid date. Tap /menu.")
            return
        is_working_val = 1 if status == "on" else 0
        status_label = "🏥 Working" if status == "on" else "🏠 Off"

        if scope == "week":
            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO shift_overrides (chat_id, override_date, is_working) VALUES (?, ?, ?)",
                    (chat_id, target.isoformat(), is_working_val),
                )
            msg = f"✅ {status_label} {target.strftime('%A %m/%d')} — override saved (this week only)."
        else:
            # Permanent: update the shifts table rotation for this weekday
            weekday = target.weekday()
            with db() as conn:
                shift = conn.execute(
                    "SELECT * FROM shifts WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
                    (chat_id,),
                ).fetchone()
            if shift:
                w1 = _json.loads(shift["week1_days"] or "[]")
                w2 = _json.loads(shift["week2_days"] or "[]")
                for week_days in (w1, w2):
                    if is_working_val and weekday not in week_days:
                        week_days.append(weekday)
                    elif not is_working_val and weekday in week_days:
                        week_days.remove(weekday)
                with db() as conn:
                    conn.execute(
                        "UPDATE shifts SET week1_days = ?, week2_days = ? WHERE chat_id = ?",
                        (_json.dumps(sorted(w1)), _json.dumps(sorted(w2)), chat_id),
                    )
                msg = f"✅ {status_label} every {target.strftime('%A')} — rotation updated."
            else:
                msg = "No schedule found. Set one up in Settings first."

        from keyboards import today_actions_kb
        await query.edit_message_text(msg, reply_markup=today_actions_kb())

    elif action.startswith("override_on") or action.startswith("override_off"):
        # Legacy quick-override buttons (kept for backward compat)
        from database import db
        from helpers import today
        from datetime import timedelta
        is_working = 1 if "on" in action else 0
        day_offset = int(parts[2]) if len(parts) > 2 else 0
        target = today() + timedelta(days=day_offset)
        label = "today" if day_offset == 0 else "tomorrow"
        status = "🏥 Working" if is_working else "🏠 Off"

        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO shift_overrides (chat_id, override_date, is_working) VALUES (?, ?, ?)",
                (chat_id, target.isoformat(), is_working),
            )
        from keyboards import today_actions_kb
        await query.edit_message_text(
            f"✅ {status} {label} ({target.strftime('%A %m/%d')}) — override saved.",
            reply_markup=today_actions_kb(),
        )


async def handle_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle capture:* callbacks."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "start"

    if action == "start":
        from keyboards import capture_menu_kb
        await query.edit_message_text(
            "➕ What are you adding?",
            reply_markup=capture_menu_kb(),
        )


async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle settings:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "view"

    if action == "view":
        await query.edit_message_text("⚙️ Settings", reply_markup=settings_kb())

    elif action == "schedule":
        from keyboards import schedule_edit_kb
        import json as _json
        from database import db
        with db() as conn:
            shift = conn.execute(
                "SELECT * FROM shifts WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
                (chat_id,)
            ).fetchone()
        if shift:
            day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
            sun_sat = [6, 0, 1, 2, 3, 4, 5]
            w1_days = _json.loads(shift["week1_days"] or "[]")
            w2_days = _json.loads(shift["week2_days"] or "[]")
            w1 = ", ".join(day_names[d] for d in sun_sat if d in w1_days)
            w2 = ", ".join(day_names[d] for d in sun_sat if d in w2_days)

            # Show 14-day grid
            from keyboards import schedule_14day_grid_kb
            grid_text = (
                f"🏥 Current Schedule\n"
                f"Shift: {shift['shift_type']}\n\n"
                f"        Sun Mon Tue Wed Thu Fri Sat\n"
                f"Wk 1:  {_week_emoji_row(w1_days)}\n"
                f"Wk 2:  {_week_emoji_row(w2_days)}\n\n"
                f"Week 1: {w1}\n"
                f"Week 2: {w2}\n\n"
                f"What do you want to change?"
            )
            text = grid_text
        else:
            text = "No schedule set yet. What do you want to configure?"
        await query.edit_message_text(text, reply_markup=schedule_edit_kb())

    elif action == "edit_shift_type":
        from keyboards import settings_shift_type_kb
        await query.edit_message_text(
            "Pick your shift hours:",
            reply_markup=settings_shift_type_kb(),
        )

    elif action == "set_shift_type":
        shift_type = parts[2] if len(parts) > 2 else "7p-7a"
        from database import db
        with db() as conn:
            conn.execute("UPDATE shifts SET shift_type = ? WHERE chat_id = ?", (shift_type, chat_id))
        await query.edit_message_text(
            f"✅ Shift updated to {shift_type}",
            reply_markup=settings_kb(),
        )

    elif action == "edit_w1":
        from keyboards import onboard_days_kb
        context.user_data["settings_editing"] = "week1"
        context.user_data["settings_selected_days"] = []
        await query.edit_message_text(
            "Tap your Week 1 work days, then hit Done:",
            reply_markup=onboard_days_kb([]),
        )

    elif action == "edit_w2":
        from keyboards import onboard_days_kb
        context.user_data["settings_editing"] = "week2"
        context.user_data["settings_selected_days"] = []
        await query.edit_message_text(
            "Tap your Week 2 work days, then hit Done:",
            reply_markup=onboard_days_kb([]),
        )

    elif action == "override":
        from keyboards import override_day_kb
        await query.edit_message_text(
            "📅 Quick Override\n\n"
            "Picked up OT? Called off? Override your schedule for today or tomorrow.",
            reply_markup=override_day_kb(),
        )

    elif action.startswith("override_on") or action.startswith("override_off"):
        from database import db
        from helpers import today
        from datetime import timedelta
        is_working = 1 if "on" in action else 0
        day_offset = int(parts[2]) if len(parts) > 2 else 0
        target = today() + timedelta(days=day_offset)
        label = "today" if day_offset == 0 else "tomorrow"
        status = "🏥 Working" if is_working else "🏠 Off"

        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO shift_overrides (chat_id, override_date, is_working) VALUES (?, ?, ?)",
                (chat_id, target.isoformat(), is_working),
            )
        await query.edit_message_text(
            f"✅ {status} {label} ({target.strftime('%A %m/%d')}) — override saved.",
            reply_markup=settings_kb(),
        )

    elif action == "notify":
        await query.edit_message_text(
            "🔔 Notification window: 5 AM – 5 PM ET\n"
            "Afternoon digest: 2 PM\n"
            "Evening check-in: 10 PM\n\n"
            "(Editing notification times coming soon)",
            reply_markup=settings_kb(),
        )

    elif action == "payday":
        from keyboards import payday_picker_kb
        from database import db
        with db() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE chat_id = ? AND key = 'payday_type'",
                (chat_id,)
            ).fetchone()
        current = row["value"] if row else "weekly_friday"
        labels = {
            "weekly_friday": "Every Friday",
            "biweekly_friday": "Every Other Friday",
            "first_fifteenth": "1st & 15th",
            "custom": "Custom day",
        }
        await query.edit_message_text(
            f"💰 PAYDAY SETTINGS\n\n"
            f"Current: {labels.get(current, current)}\n\n"
            "Pick your payday schedule:",
            reply_markup=payday_picker_kb(),
        )

    elif action == "setpayday":
        # settings:setpayday:{val}
        from database import db
        val = parts[2] if len(parts) > 2 else "weekly_friday"
        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (chat_id, key, value) VALUES (?, 'payday_type', ?)",
                (chat_id, val),
            )
        labels = {
            "weekly_friday": "Every Friday",
            "biweekly_friday": "Every Other Friday",
            "first_fifteenth": "1st & 15th of month",
            "custom": "Custom day of month",
        }
        await query.edit_message_text(
            f"✅ Payday set to: {labels.get(val, val)}",
            reply_markup=settings_kb(),
        )

    elif action == "touches":
        from keyboards import touch_frequency_kb
        from database import db
        with db() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE chat_id = ? AND key = 'touch_frequency'",
                (chat_id,)
            ).fetchone()
        current = int(row["value"]) if row else 2
        label = {0: "Never", 1: "Once", 2: "Twice", 3: "3x", 4: "4x", 6: "6x", 8: "8x"}.get(current, f"{current}x")
        await query.edit_message_text(
            f"💬 CHECK-IN FREQUENCY\n\nCurrently: {label} a day\n\n"
            "How often do you want Maurice to reach out?",
            reply_markup=touch_frequency_kb(current),
        )

    elif action == "settouches":
        freq = parts[2] if len(parts) > 2 else "2"
        try:
            freq_int = int(freq)
        except ValueError:
            freq_int = 2
        from database import db
        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (chat_id, key, value) VALUES (?, 'touch_frequency', ?)",
                (chat_id, str(freq_int)),
            )
        from keyboards import touch_frequency_kb
        label = {0: "Never", 1: "Once", 2: "Twice", 3: "3x", 4: "4x", 6: "6x", 8: "8x"}.get(freq_int, f"{freq_int}x")
        await query.edit_message_text(
            f"✅ Set to {label} a day.",
            reply_markup=touch_frequency_kb(freq_int),
        )

    elif action == "toggles":
        from keyboards import feature_toggles_kb
        from database import db
        # Load current toggles from settings table
        toggles = {}
        with db() as conn:
            rows = conn.execute(
                "SELECT key, value FROM settings WHERE chat_id = ? AND key LIKE 'toggle_%'",
                (chat_id,)
            ).fetchall()
        for row in rows:
            key = row["key"].replace("toggle_", "")
            toggles[key] = row["value"] == "1"
        await query.edit_message_text(
            "🛠 FEATURE TOGGLES\n\n"
            "Tap a feature to turn it on/off:\n"
            "(✅ = on, ❌ = off)",
            reply_markup=feature_toggles_kb(toggles),
        )

    elif action == "toggle":
        # settings:toggle:{feature_key}
        feature_key = parts[2] if len(parts) > 2 else ""
        from keyboards import feature_toggles_kb
        from database import db
        # Toggle the value
        with db() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE chat_id = ? AND key = ?",
                (chat_id, f"toggle_{feature_key}"),
            ).fetchone()
            if row:
                new_val = "0" if row["value"] == "1" else "1"
                conn.execute(
                    "UPDATE settings SET value = ? WHERE chat_id = ? AND key = ?",
                    (new_val, chat_id, f"toggle_{feature_key}"),
                )
            else:
                # First toggle — default was ON, so set to OFF
                new_val = "0"
                conn.execute(
                    "INSERT INTO settings (chat_id, key, value) VALUES (?, ?, ?)",
                    (chat_id, f"toggle_{feature_key}", new_val),
                )
        # Reload toggles and re-show
        toggles = {}
        with db() as conn:
            rows = conn.execute(
                "SELECT key, value FROM settings WHERE chat_id = ? AND key LIKE 'toggle_%'",
                (chat_id,)
            ).fetchall()
        for row in rows:
            key = row["key"].replace("toggle_", "")
            toggles[key] = row["value"] == "1"
        status_word = "ON" if new_val == "1" else "OFF"
        await query.edit_message_text(
            f"🛠 FEATURE TOGGLES\n\n"
            f"{feature_key.replace('_', ' ').title()}: {status_word}\n\n"
            f"Tap a feature to turn it on/off:",
            reply_markup=feature_toggles_kb(toggles),
        )


# ── TEXT MESSAGE HANDLER — routes typed text to active module ──

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Route text messages to whichever module is awaiting input.
    Falls through each handler until one claims the message.
    """
    # Try each module's text handler in order
    handlers = [
        handle_field_edit_text,   # Universal field editor (highest priority)
        handle_appt_text,         # Appointment multi-step flow
        handle_onboard_text,
        handle_settings_text,
        handle_bill_text,
        handle_partner_text,
        handle_car_text,
        handle_cred_text,
        handle_med_text,
        handle_note_text,
    ]

    for handler in handlers:
        try:
            consumed = await handler(update, context)
        except Exception as e:
            # Handler crashed mid-flow. Log it but DON'T fall through to menu —
            # that was the original bug where a crash made the bot show the menu
            # in place of the expected response (e.g. bill name → main menu).
            logger.error(
                f"Handler {handler.__name__} crashed on text '{update.message.text[:30]}': {e}",
                exc_info=True
            )
            # Clear onboard_step so the next text doesn't re-trigger onboarding recovery
            from database import update_user as _uu
            _uu(update.effective_chat.id, onboard_step=None)
            await update.message.reply_text(
                "Something went sideways. Tap wherever you left off or type /menu."
            )
            return
        if consumed:
            return

    # No module claimed this text — clear any stale onboard_step before showing menu
    from database import update_user
    update_user(update.effective_chat.id, onboard_step=None)
    await update.message.reply_text(
        "Not sure what to do with that. Tap a button or type /menu.",
        reply_markup=main_menu_kb(),
    )


# ── SCHEDULED JOBS ──

def setup_jobs(app):
    """Register all scheduled jobs."""
    jq = app.job_queue

    # Timezone for all jobs
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/New_York")

    # Daily reset at midnight ET
    jq.run_daily(daily_reset, time=dt_time(0, 1, tzinfo=tz), name="daily_reset")

    # Afternoon digest at 2 PM ET
    jq.run_daily(afternoon_digest, time=dt_time(DAILY_DIGEST_HOUR, 0, tzinfo=tz), name="afternoon_digest")

    # Evening check-in at 10 PM ET
    jq.run_daily(evening_checkin, time=dt_time(EVENING_CHECKIN_HOUR, 0, tzinfo=tz), name="evening_checkin")

    # Med nag every 2 hours during notification window (5 AM - 5 PM ET)
    for hour in range(5, 17, 2):  # 5, 7, 9, 11, 1, 3
        jq.run_daily(med_nag, time=dt_time(hour, 30, tzinfo=tz), name=f"med_nag_{hour}")

    # Bill nag on Fridays (payday) every 3 hours
    for hour in range(9, 18, 3):  # 9, 12, 3
        jq.run_daily(bill_nag, time=dt_time(hour, 0, tzinfo=tz), name=f"bill_nag_{hour}")

    # Weekly digest Sunday at noon ET
    jq.run_daily(
        weekly_digest,
        time=dt_time(WEEKLY_DIGEST_HOUR, 0, tzinfo=tz),
        days=(WEEKLY_DIGEST_DAY,),
        name="weekly_digest",
    )

    # Daily touches: morning at 3 PM ET, evening at 10 PM ET
    # Frequency controlled per-user via settings:touches
    jq.run_daily(morning_heartbeat, time=dt_time(15, 0, tzinfo=tz), name="morning_heartbeat")
    jq.run_daily(evening_touch, time=dt_time(22, 0, tzinfo=tz), name="evening_touch")

    # Appointment reminders — hourly during notification window (5 AM - 5 PM ET)
    for hour in range(5, 17):
        jq.run_daily(
            appointment_reminder_check,
            time=dt_time(hour, 15, tzinfo=tz),
            name=f"appt_remind_{hour}",
        )

    logger.info("Scheduled jobs registered")


# ── HEALTH CHECK (keeps Railway from killing the process) ──

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *args):
        pass  # silence health check logs

def _start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    logger.info(f"Health check listening on port {port}")
    server.serve_forever()


# ── MAIN ──

def main():
    # Start health check FIRST so Railway sees us as healthy immediately
    health_thread = threading.Thread(target=_start_health_server, daemon=True)
    health_thread.start()
    logger.info("Health server started, initializing bot...")

    # Force-kill any other polling session before we start.
    # Railway briefly runs old + new instances during deploys.
    # We must wait for the old one to fully die before polling.
    import httpx
    import time

    logger.info("Waiting for old instance to release polling...")
    for attempt in range(12):  # Try for up to 60 seconds
        try:
            httpx.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
                params={"drop_pending_updates": True},
                timeout=10,
            )
            # Try a getUpdates — if it succeeds without 409, we own the session
            resp = httpx.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": -1, "limit": 1, "timeout": 1},
                timeout=15,
            )
            if resp.status_code == 200 and resp.json().get("ok"):
                logger.info(f"Polling session acquired on attempt {attempt + 1}.")
                break
            elif resp.status_code == 409:
                logger.info(f"Attempt {attempt + 1}: old instance still polling, waiting 5s...")
                time.sleep(5)
            else:
                logger.warning(f"Unexpected response: {resp.status_code}")
                time.sleep(5)
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} error: {e}")
            time.sleep(5)
    else:
        logger.warning("Could not acquire polling after 60s — starting anyway.")

    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("version", _version_command))

    # Button presses — single router handles everything
    app.add_handler(CallbackQueryHandler(button_router))

    # Text messages — routed to active module
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # Scheduled jobs
    setup_jobs(app)

    logger.info(f"Butler Bot {BOT_VERSION} starting...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()
