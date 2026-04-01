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
from modules.car import car_callback, handle_car_text
from modules.credentials import creds_callback, handle_cred_text
from modules.meds import meds_callback, handle_med_text
from modules.notes import notes_callback, handle_note_text
from modules.appointments import appts_callback, handle_appt_text
from modules.settings_handlers import handle_settings_text, handle_settings_day_select
from modules.field_editor import handle_field_edit_text
from modules.scheduler import (
    daily_reset, afternoon_digest, evening_checkin,
    med_nag, bill_nag, weekly_digest, appointment_reminder_check,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ── COMMAND HANDLERS (minimal — just /start and /menu) ──

BOT_VERSION = "2.2.0-ux-overhaul"

def _week_emoji_row(days: list[int]) -> str:
    """Build a Sun-Sat emoji row for schedule display."""
    sun_sat = [6, 0, 1, 2, 3, 4, 5]
    return "  ".join("🏥" if d in days else "🏠" for d in sun_sat)

async def _version_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug: show which version is actually running."""
    await update.message.reply_text(f"🔧 Butler Bot {BOT_VERSION}\nBuild: 2026-03-17T0620Z\nDeploy: nixpacks")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The /menu command — main entry point."""
    from database import ensure_user
    chat_id = update.effective_chat.id
    name = update.effective_user.first_name
    is_onboarded = ensure_user(chat_id, name)

    if not is_onboarded:
        await start_command(update, context)
        return

    # Clear any stale input state so we start fresh
    _clear_input_state(context)
    await update.message.reply_text(
        "What do you need? 🫡",
        reply_markup=main_menu_kb(),
    )


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
    _is_settings_day_pick = (
        context.user_data.get("settings_editing")
        and data.startswith("onboard:")
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

    # If user is editing settings and taps day-picker, route to settings handler
    if context.user_data.get("settings_editing") and prefix == "onboard":
        await handle_settings_day_select(update, context)
        return

    # Handle noop buttons (informational headers in grids)
    if data == "noop":
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
    query = update.callback_query
    await query.answer()
    # Ensure all input state is wiped when returning to menu
    _clear_input_state(context)
    await query.edit_message_text("What do you need? 🫡", reply_markup=main_menu_kb())


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
            "Quick change for today or tomorrow?\n"
            "Or edit your full rotation below.",
            reply_markup=alter_schedule_kb(),
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
        context.user_data["awaiting"] = "settings_shift_type"
        await query.edit_message_text(
            "What are your shift hours?\n(e.g. '7p-7a', '7a-7p', '3p-11p')"
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
        await query.edit_message_text(
            "💰 Payday: Every Friday\n\n"
            "(Editing payday settings coming soon)",
            reply_markup=settings_kb(),
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
        consumed = await handler(update, context)
        if consumed:
            return

    # No module claimed it — show menu hint
    logger.warning(f"[TEXT-FALLBACK] No handler claimed text='{update.message.text.strip()[:30]}' "
                   f"awaiting={context.user_data.get('awaiting')} chat={update.effective_chat.id}")
    await update.message.reply_text(
        "Tap /menu to get started, or use the buttons above. 🫡",
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
