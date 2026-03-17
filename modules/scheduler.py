"""
Automated reminder engine.
Handles: daily digests, med nags, bill nags, payday alerts,
car/credential countdowns, daily taken_today resets,
shift-aware appointment reminders.
"""
import json
import logging
from datetime import date, time, timedelta, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import db
from helpers import (
    now, today, days_until, friendly_date, urgency_emoji, format_money,
    is_payday, next_payday, is_work_day,
)

from keyboards import (
    main_menu_kb, today_actions_kb, followup_kb, meds_list_kb,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# DAILY RESET (runs at midnight ET)
# ═══════════════════════════════════════════════════════

async def daily_reset(context: ContextTypes.DEFAULT_TYPE):
    """Reset daily flags: meds taken, bill cycle on 1st of month."""
    logger.info("Running daily reset")
    with db() as conn:
        # Reset medication taken_today
        conn.execute("UPDATE medications SET taken_today = 0")

        # On 1st of month, reset bill paid_this_cycle
        if today().day == 1:
            conn.execute("UPDATE bills SET paid_this_cycle = 0")
            logger.info("Monthly bill cycle reset")


# ═══════════════════════════════════════════════════════
# AFTERNOON DIGEST (2 PM ET — wake-up check-in)
# ═══════════════════════════════════════════════════════

async def afternoon_digest(context: ContextTypes.DEFAULT_TYPE):
    """Send afternoon summary to all users."""
    logger.info("Sending afternoon digest")
    with db() as conn:
        users = conn.execute("SELECT * FROM users WHERE onboarded = 1").fetchall()

    for user in users:
        try:
            await _send_digest(context, user["chat_id"], "afternoon")
        except Exception as e:
            logger.error(f"Digest failed for {user['chat_id']}: {e}")


async def evening_checkin(context: ContextTypes.DEFAULT_TYPE):
    """Send evening check-in (10 PM ET — during night shift)."""
    logger.info("Sending evening check-in")
    with db() as conn:
        users = conn.execute("SELECT * FROM users WHERE onboarded = 1").fetchall()

    for user in users:
        try:
            await _send_digest(context, user["chat_id"], "evening")
        except Exception as e:
            logger.error(f"Evening check-in failed for {user['chat_id']}: {e}")


async def _send_digest(context: ContextTypes.DEFAULT_TYPE, chat_id: int, time_of_day: str):
    """Build and send a digest message."""
    d = today()
    lines = []

    if time_of_day == "afternoon":
        lines.append("☀️ AFTERNOON CHECK-IN\n")
    else:
        lines.append("🌙 EVENING CHECK-IN\n")

    # Shift info
    with db() as conn:
        shift = conn.execute(
            "SELECT * FROM shifts WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
            (chat_id,)
        ).fetchone()

    if shift and shift["week1_days"]:
        w1 = json.loads(shift["week1_days"])
        w2 = json.loads(shift["week2_days"] or "[]") or w1
        try:
            anchor = shift["anchor_date"] or "2026-03-30"
        except (IndexError, KeyError):
            anchor = "2026-03-30"
        stype = shift["shift_type"] if shift["shift_type"] else "7p-7a"
        if is_work_day(d, anchor, w1, w2):
            lines.append(f"🏥 You're working tonight ({stype})")
        else:
            tomorrow = d + timedelta(days=1)
            if is_work_day(tomorrow, anchor, w1, w2):
                lines.append("🏥 Work tomorrow — get some rest")
            else:
                lines.append("🏠 Off today")
    lines.append("")

    # Meds check
    with db() as conn:
        meds = conn.execute(
            "SELECT * FROM medications WHERE chat_id = ?", (chat_id,)
        ).fetchall()
    if meds:
        untaken = [m for m in meds if not m["taken_today"]]
        if untaken:
            names = ", ".join(m["name"] for m in untaken)
            lines.append(f"💊 MEDS NOT TAKEN: {names} ⚠️")
        else:
            lines.append("💊 Meds: All taken ✅")
        lines.append("")

    # Payday / Bills
    if is_payday(d):
        with db() as conn:
            unpaid = conn.execute(
                "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0",
                (chat_id,)
            ).fetchall()
        if unpaid:
            total = sum((b["amount"] or 0) for b in unpaid)
            lines.append(f"💰 PAYDAY — {len(unpaid)} bills unpaid ({format_money(total)})")
            for b in unpaid:
                lines.append(f"  ⬜ {b['name']} {format_money(b['amount'])}")
            lines.append("")
    else:
        np = next_payday()
        days_to = days_until(np)
        if days_to <= 2:
            lines.append(f"💰 Payday {friendly_date(np)}")
            lines.append("")

    # Urgent bills (due within 3 days)
    with db() as conn:
        bills = conn.execute(
            "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0",
            (chat_id,)
        ).fetchall()
    for b in bills:
        if b["due_day"]:
            due = d.replace(day=min(b["due_day"], 28))
            if due < d:
                if due.month < 12:
                    due = due.replace(month=due.month + 1)
                else:
                    due = due.replace(year=due.year + 1, month=1)
            if 0 < (due - d).days <= 3:
                lines.append(f"⚠️ {b['name']} due {friendly_date(due)}")

    # Car events due within 14 days
    with db() as conn:
        car = conn.execute(
            "SELECT * FROM car_events WHERE chat_id = ? AND done = 0",
            (chat_id,)
        ).fetchall()
    for e in car:
        due = date.fromisoformat(e["due_date"])
        delta = days_until(due)
        if delta <= 14:
            urg = urgency_emoji(delta)
            lines.append(f"{urg} 🚗 {e['description']} — {friendly_date(due)}")

    # Credential expiries within 60 days
    with db() as conn:
        creds = conn.execute(
            "SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0",
            (chat_id,)
        ).fetchall()
    for c in creds:
        exp = date.fromisoformat(c["expiry_date"])
        delta = days_until(exp)
        if delta <= 60:
            urg = urgency_emoji(delta)
            lines.append(f"{urg} 🎓 {c['name']} expires {friendly_date(exp)}")

    # Appointments within 7 days
    from modules.appointments import get_upcoming_appointments, CATEGORY_EMOJI
    upcoming_appts = get_upcoming_appointments(chat_id, days_ahead=7)
    if upcoming_appts:
        lines.append("")
        lines.append("📅 UPCOMING APPOINTMENTS:")
        for a in upcoming_appts:
            from datetime import date as _date
            event_date = _date.fromisoformat(a["event_date"])
            delta = days_until(event_date)
            urg = urgency_emoji(delta)
            time_str = f" at {a['event_time']}" if a.get("event_time") else ""
            try:
                cat = a["category"] or "other"
            except (IndexError, KeyError):
                cat = "other"
            cat_emoji = CATEGORY_EMOJI.get(cat, "📅")
            lines.append(f"  {urg} {cat_emoji} {a['title']}{time_str} — {friendly_date(event_date)}")

    # Partner dates within 7 days
    with db() as conn:
        pdates = conn.execute("""
            SELECT pd.*, p.name as partner_name, p.emoji
            FROM partner_dates pd
            JOIN partners p ON pd.partner_id = p.id
            WHERE pd.chat_id = ?
        """, (chat_id,)).fetchall()
    for pd_row in pdates:
        dv = pd_row["date_value"]
        try:
            if len(dv) == 5:
                target = date(d.year, int(dv[:2]), int(dv[3:]))
                if target < d:
                    target = date(d.year + 1, int(dv[:2]), int(dv[3:]))
            else:
                target = date.fromisoformat(dv)
            delta = days_until(target)
            if 0 <= delta <= 7:
                emoji = pd_row["emoji"] or "💜"
                try:
                    label = pd_row["label"] or pd_row["date_type"]
                except (IndexError, KeyError):
                    label = pd_row["date_type"]
                lines.append(f"{emoji} {pd_row['partner_name']} — {label} {friendly_date(target)}")
        except (ValueError, TypeError):
            pass

    if len(lines) <= 3:
        lines.append("Nothing urgent. You're good. 🫡")

    text = "\n".join(lines)
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=today_actions_kb())


# ═══════════════════════════════════════════════════════
# MED NAG (every 2 hours during notification window)
# ═══════════════════════════════════════════════════════

async def med_nag(context: ContextTypes.DEFAULT_TYPE):
    """Check if meds are untaken and nag."""
    logger.info("Running med nag check")
    with db() as conn:
        users = conn.execute("SELECT * FROM users WHERE onboarded = 1").fetchall()

    for user in users:
        chat_id = user["chat_id"]
        with db() as conn:
            untaken = conn.execute(
                "SELECT * FROM medications WHERE chat_id = ? AND taken_today = 0",
                (chat_id,)
            ).fetchall()

        if untaken:
            names = ", ".join(m["name"] for m in untaken)
            meds_list = [dict(m) for m in untaken]
            text = f"💊 Hey. You still haven't taken: {names}\n\nDon't make me ask again. 😤"
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=meds_list_kb(meds_list),
            )


# ═══════════════════════════════════════════════════════
# BILL NAG (on payday, every 3 hours until all paid)
# ═══════════════════════════════════════════════════════

async def bill_nag(context: ContextTypes.DEFAULT_TYPE):
    """On payday, nag about unpaid bills."""
    d = today()
    if not is_payday(d):
        return

    logger.info("Running payday bill nag")
    with db() as conn:
        users = conn.execute("SELECT * FROM users WHERE onboarded = 1").fetchall()

    for user in users:
        chat_id = user["chat_id"]
        with db() as conn:
            unpaid = conn.execute(
                "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0",
                (chat_id,)
            ).fetchall()

        if unpaid:
            total = sum((b["amount"] or 0) for b in unpaid)
            text = (
                f"💰 It's payday and you still have {len(unpaid)} unpaid bills "
                f"({format_money(total)}).\n\n"
                f"Handle your business. 💪"
            )
            from keyboards import bills_list_kb
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=bills_list_kb([dict(b) for b in unpaid]),
            )


# ═══════════════════════════════════════════════════════
# WEEKLY DIGEST (Sunday noon)
# ═══════════════════════════════════════════════════════

async def weekly_digest(context: ContextTypes.DEFAULT_TYPE):
    """Send comprehensive weekly summary."""
    logger.info("Sending weekly digest")
    with db() as conn:
        users = conn.execute("SELECT * FROM users WHERE onboarded = 1").fetchall()

    for user in users:
        chat_id = user["chat_id"]
        try:
            d = today()
            lines = ["📆 WEEKLY SUMMARY\n"]

            # Work days this week
            with db() as conn:
                shift = conn.execute(
                    "SELECT * FROM shifts WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
                    (chat_id,)
                ).fetchone()

            if shift and shift["week1_days"]:
                w1 = json.loads(shift["week1_days"])
                w2 = json.loads(shift["week2_days"] or "[]") or w1
                try:
                    anchor = shift["anchor_date"] or "2026-03-30"
                except (IndexError, KeyError):
                    anchor = "2026-03-30"
                start = d - timedelta(days=d.weekday())  # Monday
                work_count = 0
                day_names = []
                for i in range(7):
                    check = start + timedelta(days=i)
                    if is_work_day(check, anchor, w1, w2):
                        work_count += 1
                        day_names.append(check.strftime("%a"))
                lines.append(f"🏥 This week: {work_count} shifts ({', '.join(day_names)})")
                lines.append("")

            # Bills summary
            with db() as conn:
                bills = conn.execute("SELECT * FROM bills WHERE chat_id = ?", (chat_id,)).fetchall()
            paid = [b for b in bills if b["paid_this_cycle"]]
            unpaid = [b for b in bills if not b["paid_this_cycle"]]
            total_unpaid = sum((b["amount"] or 0) for b in unpaid)
            lines.append(f"💸 Bills: {len(paid)} paid, {len(unpaid)} remaining ({format_money(total_unpaid)})")

            # Car / Creds approaching
            with db() as conn:
                car = conn.execute(
                    "SELECT * FROM car_events WHERE chat_id = ? AND done = 0", (chat_id,)
                ).fetchall()
                creds = conn.execute(
                    "SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0", (chat_id,)
                ).fetchall()

            approaching = []
            for e in car:
                delta = days_until(date.fromisoformat(e["due_date"]))
                if delta <= 30:
                    approaching.append(f"🚗 {e['description']} — {friendly_date(date.fromisoformat(e['due_date']))}")
            for c in creds:
                delta = days_until(date.fromisoformat(c["expiry_date"]))
                if delta <= 90:
                    approaching.append(f"🎓 {c['name']} — expires {friendly_date(date.fromisoformat(c['expiry_date']))}")

            if approaching:
                lines.append("\n📋 Coming up:")
                for item in approaching:
                    lines.append(f"  {item}")

            # Appointments this week
            from modules.appointments import get_upcoming_appointments as _get_appts
            week_appts = _get_appts(chat_id, days_ahead=7)
            if week_appts:
                lines.append("\n📅 Appointments this week:")
                for a in week_appts:
                    event_date = date.fromisoformat(a["event_date"])
                    time_str = f" at {a['event_time']}" if a.get("event_time") else ""
                    lines.append(f"  • {a['title']}{time_str} — {friendly_date(event_date)}")

            lines.append("\nHave a good week. 🫡")
            text = "\n".join(lines)
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=main_menu_kb())
        except Exception as e:
            logger.error(f"Weekly digest failed for {chat_id}: {e}")


# ═══════════════════════════════════════════════════════
# APPOINTMENT REMINDER CHECK (hourly during notification window)
# ═══════════════════════════════════════════════════════

async def appointment_reminder_check(context: ContextTypes.DEFAULT_TYPE):
    """Check all appointments and fire reminders based on priority + shift schedule."""
    from modules.appointments import CATEGORY_EMOJI, PRIORITY_REMINDERS, CATEGORIES

    logger.info("Running appointment reminder check")
    d = today()

    with db() as conn:
        users = conn.execute("SELECT * FROM users WHERE onboarded = 1").fetchall()

    for user in users:
        chat_id = user["chat_id"]
        try:
            await _check_user_appointments(context, chat_id, d)
        except Exception as e:
            logger.error(f"Appointment reminder failed for {chat_id}: {e}")


async def _check_user_appointments(context, chat_id, d):
    """Check appointments for one user and send reminders as needed."""
    from modules.appointments import CATEGORY_EMOJI, PRIORITY_REMINDERS, CATEGORIES

    # Get shift info for tonight
    working_tonight = False
    with db() as conn:
        shift = conn.execute(
            "SELECT * FROM shifts WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
            (chat_id,)
        ).fetchone()

    if shift and shift["week1_days"]:
        w1 = json.loads(shift["week1_days"])
        w2 = json.loads(shift["week2_days"] or "[]") or w1
        try:
            anchor = shift["anchor_date"] or "2026-03-30"
        except (IndexError, KeyError):
            anchor = "2026-03-30"
        working_tonight = is_work_day(d, anchor, w1, w2)

    # Get all undone appointments with reminders enabled
    with db() as conn:
        appts = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND done = 0",
            (chat_id,)
        ).fetchall()

    for appt in appts:
        try:
            priority = appt["priority"] if appt["priority"] is not None else 2
        except (IndexError, KeyError):
            priority = 2

        if priority == 0:
            continue  # No reminders for priority 0

        try:
            reminder_level = appt["reminder_level"] or "smart"
        except (IndexError, KeyError):
            reminder_level = "smart"

        if reminder_level == "none":
            continue

        event_date = date.fromisoformat(appt["event_date"])
        days_away = (event_date - d).days

        # Determine which reminder thresholds apply for this priority
        thresholds = PRIORITY_REMINDERS.get(priority, [1, 0])

        for threshold in thresholds:
            if days_away == threshold:
                # Check if we already sent this reminder today
                reminder_key = f"appt_{threshold}d"
                if _already_sent(chat_id, appt["id"], reminder_key, d):
                    continue

                # Check if snoozed recently (within last 2 hours)
                if _recently_snoozed(chat_id, appt["id"]):
                    continue

                # Send reminder
                await _send_appointment_reminder(
                    context, chat_id, appt, days_away, working_tonight
                )
                # Log the reminder
                _log_reminder(chat_id, appt["id"], reminder_key)

        # Follow-up: if priority >= 3, event_time has passed, and not done
        if priority >= 3 and days_away == 0 and appt["event_time"]:
            current_hour = now().hour
            try:
                event_hour = int(appt["event_time"].split(":")[0])
                if current_hour > event_hour:
                    followup_key = "appt_followup"
                    if not _already_sent(chat_id, appt["id"], followup_key, d):
                        if not _recently_snoozed(chat_id, appt["id"]):
                            await _send_followup_reminder(context, chat_id, appt)
                            _log_reminder(chat_id, appt["id"], followup_key)
            except (ValueError, TypeError):
                pass
        # Follow-up for day-of with no time set (fire after noon)
        elif priority >= 3 and days_away == 0 and not appt["event_time"]:
            if now().hour >= 12:
                followup_key = "appt_followup"
                if not _already_sent(chat_id, appt["id"], followup_key, d):
                    if not _recently_snoozed(chat_id, appt["id"]):
                        await _send_followup_reminder(context, chat_id, appt)
                        _log_reminder(chat_id, appt["id"], followup_key)


def _already_sent(chat_id, appt_id, reminder_key, d) -> bool:
    """Check if a specific reminder was already sent today.
    Uses UTC date from sent_at (SQLite datetime('now') is UTC)."""
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM reminder_log WHERE chat_id = ? AND category = ? "
            "AND ref_id = ? AND date(sent_at) = date('now')",
            (chat_id, reminder_key, appt_id),
        ).fetchone()
    return row is not None


def _recently_snoozed(chat_id, appt_id) -> bool:
    """Check if the user snoozed this appointment in the last 2 hours."""
    cutoff = (now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM reminder_log WHERE chat_id = ? AND category = 'appt_snooze' "
            "AND ref_id = ? AND sent_at >= ?",
            (chat_id, appt_id, cutoff),
        ).fetchone()
    return row is not None


def _log_reminder(chat_id, appt_id, reminder_key):
    """Log that a reminder was sent."""
    with db() as conn:
        conn.execute(
            "INSERT INTO reminder_log (chat_id, category, ref_id) VALUES (?, ?, ?)",
            (chat_id, reminder_key, appt_id),
        )


async def _send_appointment_reminder(context, chat_id, appt, days_away, working_tonight):
    """Send an appointment reminder message."""
    from modules.appointments import CATEGORY_EMOJI, CATEGORIES

    try:
        cat = appt["category"] or "other"
    except (IndexError, KeyError):
        cat = "other"
    cat_emoji = CATEGORY_EMOJI.get(cat, "📋")
    cat_label = CATEGORIES.get(cat, cat)

    event_date = date.fromisoformat(appt["event_date"])

    if days_away == 0:
        header = "🚨 TODAY"
        date_label = f"TODAY ({event_date.strftime('%b %d')})"
    elif days_away == 1:
        header = "🚨 APPOINTMENT REMINDER"
        date_label = f"tomorrow ({event_date.strftime('%b %d')})"
    else:
        header = "📅 APPOINTMENT REMINDER"
        date_label = f"in {days_away} days ({event_date.strftime('%b %d')})"

    lines = [
        header,
        "",
        f"📅 {appt['title']}",
        f"   {cat_emoji} {cat_label.split(' ', 1)[-1] if ' ' in cat_label else cat_label} — {date_label}",
    ]

    if working_tonight and days_away <= 1:
        lines.append("")
        lines.append("⚠️ You're working tonight. Handle this before your shift or set time tomorrow.")

    text = "\n".join(lines)

    if days_away == 0:
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Done", callback_data=f"appts:remind_done:{appt['id']}"),
                InlineKeyboardButton("⏰ Snooze 2hrs", callback_data=f"appts:snooze2h:{appt['id']}"),
            ],
        ])
    else:
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Done", callback_data=f"appts:remind_done:{appt['id']}"),
                InlineKeyboardButton("⏰ Remind Later", callback_data=f"appts:remind_later:{appt['id']}"),
            ],
            [
                InlineKeyboardButton("📅 View Details", callback_data=f"appts:detail:{appt['id']}"),
            ],
        ])

    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)


async def _send_followup_reminder(context, chat_id, appt):
    """Send a follow-up 'did you handle it?' reminder."""
    text = (
        f"🚨 Did you handle this?\n\n"
        f"📅 {appt['title']}\n"
        f"   Scheduled for today"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Done", callback_data=f"appts:remind_done:{appt['id']}"),
            InlineKeyboardButton("⏰ Snooze 2hrs", callback_data=f"appts:snooze2h:{appt['id']}"),
        ],
    ])
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
