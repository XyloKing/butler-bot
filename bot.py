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
from modules.partners import partners_callback, handle_partner_text
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


# ═══════════════════════════════════════════════════════
# COMMAND HANDLERS (minimal — just /start and /menu)
# ═══════════════════════════════════════════════════════

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The /menu command — main entry point."""
    from database import ensure_user
    chat_id = update.effective_chat.id
    name = update.effective_user.first_name
    is_onboarded = ensure_user(chat_id, name)

    if not is_onboarded:
        await start_command(update, context)
        return

    await update.message.reply_text(
        "What do you need? 🫡",
        reply_markup=main_menu_kb(),
    )


# ═══════════════════════════════════════════════════════
# CALLBACK ROUTER — all button presses go here
# ═══════════════════════════════════════════════════════

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

    prefix = data.split(":")[0]

    # If user is editing settings and taps day-picker, route to settings handler
    if context.user_data.get("settings_editing") and prefix == "onboard":
        await handle_settings_day_select(update, context)
        return

    routers = {
        "menu":     handle_menu,
        "today":    today_view,
        "week":     week_callback,
        "bills":    bills_callback,
        "partners": partners_callback,
        "car":      car_callback,
        "creds":    creds_callback,
        "meds":     meds_callback,
        "notes":    notes_callback,
        "appts":    appts_callback,
        "capture":  handle_capture,
        "settings": handle_settings,
        "onboard":  onboard_callback,
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
    await query.edit_message_text("What do you need? 🫡", reply_markup=main_menu_kb())


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
    elif action == "appointment":
        # Legacy route — redirect to proper appointments module
        context.user_data["awaiting"] = "appt_title"
        await query.edit_message_text(
            "📅 What's the appointment or event?\n"
            "(e.g. 'Dentist', 'Railway trial ends', 'Dinner with Sam')"
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
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            w1 = ", ".join(day_names[d] for d in _json.loads(shift["week1_days"] or "[]"))
            w2 = ", ".join(day_names[d] for d in _json.loads(shift["week2_days"] or "[]"))
            text = (
                f"🏥 Current Schedule\n"
                f"Shift: {shift['shift_type']}\n"
                f"Week 1: {w1}\n"
                f"Week 2: {w2}\n\n"
                f"What do you want to change?"
            )
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


# ═══════════════════════════════════════════════════════
# TEXT MESSAGE HANDLER — routes typed text to active module
# ═══════════════════════════════════════════════════════

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
    await update.message.reply_text(
        "Tap /menu to get started, or use the buttons above. 🫡",
        reply_markup=main_menu_kb(),
    )


# ═══════════════════════════════════════════════════════
# SCHEDULED JOBS
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# HEALTH CHECK (keeps Railway from killing the process)
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    init_db()

    # Start health check server in background (Railway needs a listening port)
    health_thread = threading.Thread(target=_start_health_server, daemon=True)
    health_thread.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands (just two!)
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", menu_command))

    # Button presses — single router handles everything
    app.add_handler(CallbackQueryHandler(button_router))

    # Text messages — routed to active module
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # Scheduled jobs
    setup_jobs(app)

    logger.info("Butler Bot starting...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()
