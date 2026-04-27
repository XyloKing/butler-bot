# Butler Bot — Automated reminder engine
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""Daily digests, med nags, bill nags, payday alerts, car/credential countdowns,
shift-aware appointment reminders, morning heartbeat. All jobs respect user feature toggles."""

import logging
import random
from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import db
from helpers import (
    now, today, days_until, friendly_date, urgency_emoji, format_money,
    is_payday, next_payday, is_working, get_user_shift, get_shift_info,
    resolve_date,
)
from keyboards import main_menu_kb, today_actions_kb, meds_list_kb

logger = logging.getLogger(__name__)


def _toggle_on(chat_id: int, key: str) -> bool:
    """Check if a feature is enabled for this user. Defaults to True."""
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE chat_id = ? AND key = ?",
            (chat_id, f"toggle_{key}"),
        ).fetchone()
    return row["value"] == "1" if row else True


def _onboarded_users():
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE onboarded = 1").fetchall()


# ── Morning heartbeat (3 PM ET = wake time for 7p-7a) ───

def _touch_frequency(chat_id: int) -> int:
    """How many touches per day does this user want? Default 2."""
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE chat_id = ? AND key = 'touch_frequency'",
            (chat_id,)
        ).fetchone()
    try:
        return int(row["value"]) if row else 2
    except (ValueError, TypeError):
        return 2


async def morning_heartbeat(context: ContextTypes.DEFAULT_TYPE):
    """First daily touch at 3 PM ET (wake time for night shift workers)."""
    logger.info("Sending morning heartbeat")
    for user in _onboarded_users():
        chat_id = user["chat_id"]
        if not _toggle_on(chat_id, "morning_heartbeat"):
            continue
        try:
            await _send_touch(context, chat_id)
        except Exception as e:
            logger.error(f"Heartbeat failed for {chat_id}: {e}")


async def evening_touch(context: ContextTypes.DEFAULT_TYPE):
    """Second daily touch at 10 PM ET (start of work window)."""
    logger.info("Sending evening touch")
    for user in _onboarded_users():
        chat_id = user["chat_id"]
        if not _toggle_on(chat_id, "evening_checkin"):
            continue
        if _touch_frequency(chat_id) < 2:
            continue
        try:
            await _send_touch(context, chat_id)
        except Exception as e:
            logger.error(f"Evening touch failed for {chat_id}: {e}")


async def _send_touch(context, chat_id):
    """A phrase + most urgent item. Used for all proactive touches."""
    from modules.phrases import get_phrase, get_neutral_phrase
    d = today()

    working = is_working(chat_id, d)
    recovery = not working and is_working(chat_id, d - timedelta(days=1))

    phrase = get_phrase(working_tonight=working, recovery=recovery)
    urgent = _most_urgent_item(chat_id, d)

    lines = [phrase]
    if urgent:
        lines.append("")
        lines.append(urgent)

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        reply_markup=today_actions_kb(),
    )


def _most_urgent_item(chat_id: int, d: date) -> str | None:
    """Returns a single sentence about the most urgent pending item."""
    with db() as conn:
        # Appointments in next 2 days
        appt = conn.execute(
            "SELECT title, event_date FROM appointments WHERE chat_id = ? AND done = 0 "
            "AND event_date >= ? AND event_date <= ? ORDER BY event_date LIMIT 1",
            (chat_id, d.isoformat(), (d + timedelta(days=2)).isoformat()),
        ).fetchone()
        if appt:
            delta = (date.fromisoformat(appt["event_date"]) - d).days
            when = "today" if delta == 0 else "tomorrow"
            return f"{appt['title']} is {when}"

        # Bills due in 3 days
        bills = conn.execute(
            "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0", (chat_id,)
        ).fetchall()
        for b in bills:
            if b["due_day"]:
                due = d.replace(day=min(b["due_day"], 28))
                if due < d:
                    due = (due.replace(month=due.month + 1) if due.month < 12
                           else due.replace(year=due.year + 1, month=1))
                if 0 <= (due - d).days <= 3:
                    return f"{b['name']} is due {friendly_date(due)}"

        # Meds not taken
        untaken = conn.execute(
            "SELECT name FROM medications WHERE chat_id = ? AND taken_today = 0 LIMIT 1",
            (chat_id,),
        ).fetchone()
        if untaken:
            return f"{untaken['name']} hasn't been taken yet today"

    return None


# ── Daily reset (midnight ET) ────────────────────────────

async def daily_reset(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running daily reset")
    from modules.wellness import log_event

    skip_log: list[tuple[int, int]] = []  # (chat_id, med_id) pairs to log after the txn
    with db() as conn:
        # Before resetting meds, check who completed all meds yesterday and update streaks
        for user in _onboarded_users():
            cid = user["chat_id"]
            meds = conn.execute(
                "SELECT id, taken_today FROM medications WHERE chat_id = ?", (cid,)
            ).fetchall()
            if meds and all(m["taken_today"] for m in meds):
                conn.execute(
                    "UPDATE users SET med_streak = COALESCE(med_streak, 0) + 1 WHERE chat_id = ?",
                    (cid,),
                )
            elif meds:
                # Missed — reset streak silently (never guilt)
                conn.execute(
                    "UPDATE users SET med_streak = 0 WHERE chat_id = ?", (cid,),
                )
                # Record one skip per untaken med so the wellness engine can
                # see the gap. Logged after we close the txn to avoid nesting.
                for m in meds:
                    if not m["taken_today"]:
                        skip_log.append((cid, m["id"]))

        # Intentional: reset ALL users at midnight. Single-timezone bot; all users share the same midnight.
        conn.execute("UPDATE medications SET taken_today = 0")
        if today().day == 1:
            # Intentional: bill cycle resets globally on the 1st for all users.
            conn.execute("UPDATE bills SET paid_this_cycle = 0")
            logger.info("Monthly bill cycle reset")

    for cid, mid in skip_log:
        log_event(cid, "meds", "skipped", ref_id=mid)


# ── Afternoon digest (2 PM ET) ───────────────────────────

async def afternoon_digest(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Sending afternoon digest")
    for user in _onboarded_users():
        try:
            if _toggle_on(user["chat_id"], "afternoon_digest"):
                await _send_digest(context, user["chat_id"], "afternoon")
        except Exception as e:
            logger.error(f"Digest failed for {user['chat_id']}: {e}")


# ── Evening check-in (10 PM ET) ──────────────────────────

async def evening_checkin(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Sending evening check-in")
    for user in _onboarded_users():
        try:
            if _toggle_on(user["chat_id"], "evening_checkin"):
                await _send_digest(context, user["chat_id"], "evening")
        except Exception as e:
            logger.error(f"Evening check-in failed for {user['chat_id']}: {e}")


# ── Digest builder ────────────────────────────────────────

async def _send_digest(context: ContextTypes.DEFAULT_TYPE, chat_id: int, time_of_day: str):
    d = today()
    lines = []

    if time_of_day == "afternoon":
        lines.append("☀️ AFTERNOON CHECK-IN\n")
    else:
        lines.append("🌙 EVENING CHECK-IN\n")

    # Shift info
    shift = get_user_shift(chat_id)
    if shift:
        stype = shift["shift_type"]
        if is_working(chat_id, d):
            lines.append(f"🏥 You're working tonight ({stype})")
        elif is_working(chat_id, d + timedelta(days=1)):
            lines.append("🏥 Work tomorrow — get some rest")
        else:
            lines.append("🏠 Off today")
    lines.append("")

    # Meds
    with db() as conn:
        meds = conn.execute("SELECT * FROM medications WHERE chat_id = ?", (chat_id,)).fetchall()
    if meds:
        untaken = [m for m in meds if not m["taken_today"]]
        if untaken:
            lines.append(f"💊 Meds not taken yet: {', '.join(m['name'] for m in untaken)}")
        else:
            lines.append("💊 Meds: All taken ✅")
        lines.append("")

    # Payday / bills
    if is_payday(d):
        with db() as conn:
            unpaid = conn.execute(
                "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0", (chat_id,)
            ).fetchall()
        if unpaid:
            total = sum((b["amount"] or 0) for b in unpaid)
            lines.append(f"💰 PAYDAY — {len(unpaid)} bills unpaid ({format_money(total)})")
            for b in unpaid:
                lines.append(f"  ⬜ {b['name']} {format_money(b['amount'])}")
            lines.append("")
    else:
        np = next_payday()
        if days_until(np) <= 2:
            lines += [f"💰 Payday {friendly_date(np)}", ""]

    # Urgent bills (due within 3 days)
    with db() as conn:
        bills = conn.execute(
            "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0", (chat_id,)
        ).fetchall()
    for b in bills:
        if b["due_day"]:
            due = d.replace(day=min(b["due_day"], 28))
            if due < d:
                due = due.replace(month=due.month + 1) if due.month < 12 else due.replace(year=due.year + 1, month=1)
            if 0 < (due - d).days <= 3:
                lines.append(f"⚠️ {b['name']} due {friendly_date(due)}")

    # Car events (14 days)
    with db() as conn:
        for e in conn.execute("SELECT * FROM car_events WHERE chat_id = ? AND done = 0", (chat_id,)).fetchall():
            try:
                due = date.fromisoformat(e["due_date"])
            except (ValueError, TypeError):
                continue
            delta = days_until(due)
            if delta <= 14:
                lines.append(f"{urgency_emoji(delta)} 🚗 {e['description']} — {friendly_date(due)}")

    # Credentials (60 days)
    with db() as conn:
        for c in conn.execute("SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0", (chat_id,)).fetchall():
            try:
                exp = date.fromisoformat(c["expiry_date"])
            except (ValueError, TypeError):
                continue
            delta = days_until(exp)
            if delta <= 60:
                lines.append(f"{urgency_emoji(delta)} 🎓 {c['name']} expires {friendly_date(exp)}")

    # Appointments (7 days)
    from modules.appointments import get_upcoming_appointments, CATEGORY_EMOJI
    upcoming_appts = get_upcoming_appointments(chat_id, days_ahead=7)
    if upcoming_appts:
        lines += ["", "📅 UPCOMING APPOINTMENTS:"]
        for a in upcoming_appts:
            event_date = date.fromisoformat(a["event_date"])
            time_str = f" at {a['event_time']}" if a.get("event_time") else ""
            cat_emoji = CATEGORY_EMOJI.get(a.get("category") or "other", "📅")
            lines.append(f"  {urgency_emoji(days_until(event_date))} {cat_emoji} {a['title']}{time_str} — {friendly_date(event_date)}")

    # Partner dates (7 days)
    with db() as conn:
        pdates = conn.execute("""
            SELECT pd.*, p.name as partner_name, p.emoji
            FROM partner_dates pd JOIN partners p ON pd.partner_id = p.id
            WHERE pd.chat_id = ?
        """, (chat_id,)).fetchall()
    for pd_row in pdates:
        target = resolve_date(pd_row["date_value"], d)
        if target and 0 <= days_until(target) <= 7:
            emoji = pd_row.get("emoji") or "💜"
            label = pd_row.get("label") or pd_row["date_type"]
            lines.append(f"{emoji} {pd_row['partner_name']} — {label} {friendly_date(target)}")

    # Quality-of-life suggestions
    from modules.suggestions import get_suggestions
    suggestions = get_suggestions(chat_id, time_of_day)
    if suggestions:
        lines += ["", "💡 SUGGESTIONS:"]
        for s in suggestions:
            lines.append(f"  {s}")

    if len(lines) <= 3:
        lines.append("Nothing urgent. You're good. 🫡")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n[...truncated — tap Menu to see more]"
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=today_actions_kb())


# ── Med nag (every 2 hrs during notification window) ─────

async def med_nag(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running med nag check")
    for user in _onboarded_users():
        chat_id = user["chat_id"]
        if not _toggle_on(chat_id, "med_reminders"):
            continue
        with db() as conn:
            untaken = conn.execute(
                "SELECT * FROM medications WHERE chat_id = ? AND taken_today = 0", (chat_id,)
            ).fetchall()
        if untaken:
            names = ", ".join(m["name"] for m in untaken)
            await context.bot.send_message(
                chat_id=chat_id,
                text=random.choice([
                    f"💊 Still there when you're ready: {names}",
                    f"💊 No rush — just a heads up: {names}",
                    f"💊 Whenever you get a chance: {names}",
                ]),
                reply_markup=meds_list_kb([dict(m) for m in untaken]),
            )


# ── Bill nag (payday, every 3 hrs) ───────────────────────

async def bill_nag(context: ContextTypes.DEFAULT_TYPE):
    if not is_payday(today()):
        return
    logger.info("Running payday bill nag")
    for user in _onboarded_users():
        chat_id = user["chat_id"]
        if not _toggle_on(chat_id, "bill_reminders"):
            continue
        with db() as conn:
            unpaid = conn.execute(
                "SELECT * FROM bills WHERE chat_id = ? AND paid_this_cycle = 0", (chat_id,)
            ).fetchall()
        if unpaid:
            total = sum((b["amount"] or 0) for b in unpaid)
            from keyboards import bills_list_kb
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"💰 It's payday and you have {len(unpaid)} unpaid bills ({format_money(total)}).\n\nHere's what's outstanding whenever you're ready.",
                reply_markup=bills_list_kb([dict(b) for b in unpaid]),
            )


# ── Weekly digest (Sunday noon) ───────────────────────────

async def weekly_digest(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Sending weekly digest")
    for user in _onboarded_users():
        chat_id = user["chat_id"]
        if not _toggle_on(chat_id, "weekly_digest"):
            continue
        try:
            await _send_weekly(context, chat_id)
        except Exception as e:
            logger.error(f"Weekly digest failed for {chat_id}: {e}")


async def _send_weekly(context, chat_id):
    d = today()
    lines = ["📆 WEEKLY SUMMARY\n"]

    shift = get_user_shift(chat_id)
    if shift:
        start = d - timedelta(days=(d.weekday() + 1) % 7)  # Sunday
        work_count = sum(1 for i in range(7)
                         if is_working(chat_id, start + timedelta(days=i)))
        work_names = [
            (start + timedelta(days=i)).strftime("%a")
            for i in range(7) if is_working(chat_id, start + timedelta(days=i))
        ]
        lines += [f"🏥 This week: {work_count} shifts ({', '.join(work_names)})", ""]

    with db() as conn:
        bills = conn.execute("SELECT * FROM bills WHERE chat_id = ?", (chat_id,)).fetchall()
    paid = [b for b in bills if b["paid_this_cycle"]]
    unpaid = [b for b in bills if not b["paid_this_cycle"]]
    total_unpaid = sum((b["amount"] or 0) for b in unpaid)
    lines.append(f"💸 Bills: {len(paid)} paid, {len(unpaid)} remaining ({format_money(total_unpaid)})")

    # Approaching deadlines
    approaching = []
    with db() as conn:
        for e in conn.execute("SELECT * FROM car_events WHERE chat_id = ? AND done = 0", (chat_id,)).fetchall():
            try:
                due = date.fromisoformat(e["due_date"])
            except (ValueError, TypeError):
                continue
            delta = days_until(due)
            if delta <= 30:
                approaching.append(f"🚗 {e['description']} — {friendly_date(due)}")
        for c in conn.execute("SELECT * FROM credentials WHERE chat_id = ? AND renewed = 0", (chat_id,)).fetchall():
            try:
                exp = date.fromisoformat(c["expiry_date"])
            except (ValueError, TypeError):
                continue
            delta = days_until(exp)
            if delta <= 90:
                approaching.append(f"🎓 {c['name']} — expires {friendly_date(exp)}")
    if approaching:
        lines.append("\n📋 Coming up:")
        lines += [f"  {item}" for item in approaching]

    from modules.appointments import get_upcoming_appointments
    week_appts = get_upcoming_appointments(chat_id, days_ahead=7)
    if week_appts:
        lines.append("\n📅 Appointments this week:")
        for a in week_appts:
            time_str = f" at {a['event_time']}" if a.get("event_time") else ""
            try:
                lines.append(f"  • {a['title']}{time_str} — {friendly_date(date.fromisoformat(a['event_date']))}")
            except (ValueError, TypeError):
                lines.append(f"  • {a['title']}{time_str}")

    lines.append("\nHave a good week. 🫡")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n[...truncated — tap Menu to see more]"
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=main_menu_kb())


# ── Appointment reminders (hourly) ────────────────────────

async def appointment_reminder_check(context: ContextTypes.DEFAULT_TYPE):
    from modules.appointments import CATEGORY_EMOJI, PRIORITY_REMINDERS, CATEGORIES
    logger.info("Running appointment reminder check")
    d = today()
    for user in _onboarded_users():
        chat_id = user["chat_id"]
        if not _toggle_on(chat_id, "appt_reminders"):
            continue
        try:
            await _check_user_appointments(context, chat_id, d)
        except Exception as e:
            logger.error(f"Appointment reminder failed for {chat_id}: {e}")


async def _check_user_appointments(context, chat_id, d):
    from modules.appointments import CATEGORY_EMOJI, PRIORITY_REMINDERS, CATEGORIES

    working_tonight = is_working(chat_id, d)

    with db() as conn:
        appts = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND done = 0", (chat_id,)
        ).fetchall()

    for appt in appts:
        priority = appt.get("priority") or 2
        if priority == 0:
            continue
        reminder_level = appt.get("reminder_level") or "smart"
        if reminder_level == "none":
            continue

        event_date = date.fromisoformat(appt["event_date"])
        days_away = (event_date - d).days
        thresholds = PRIORITY_REMINDERS.get(priority, [1, 0])

        for threshold in thresholds:
            if days_away == threshold:
                key = f"appt_{threshold}d"
                if _already_sent(chat_id, appt["id"], key, d):
                    continue
                if _recently_snoozed(chat_id, appt["id"]):
                    continue
                await _send_appointment_reminder(context, chat_id, appt, days_away, working_tonight)
                _log_reminder(chat_id, appt["id"], key)

        # Follow-up for high priority
        if priority >= 3 and days_away == 0:
            await _maybe_followup(context, chat_id, appt, d)


async def _maybe_followup(context, chat_id, appt, d):
    key = "appt_followup"
    if _already_sent(chat_id, appt["id"], key, d) or _recently_snoozed(chat_id, appt["id"]):
        return
    if appt["event_time"]:
        try:
            if now().hour > int(appt["event_time"].split(":")[0]):
                await _send_followup_reminder(context, chat_id, appt)
                _log_reminder(chat_id, appt["id"], key)
        except (ValueError, TypeError):
            pass
    elif now().hour >= 12:
        await _send_followup_reminder(context, chat_id, appt)
        _log_reminder(chat_id, appt["id"], key)


def _already_sent(chat_id, appt_id, key, d) -> bool:
    with db() as conn:
        return conn.execute(
            "SELECT id FROM reminder_log WHERE chat_id = ? AND category = ? "
            "AND ref_id = ? AND date(sent_at) = date('now')",
            (chat_id, key, appt_id),
        ).fetchone() is not None


def _recently_snoozed(chat_id, appt_id) -> bool:
    cutoff = (now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    with db() as conn:
        return conn.execute(
            "SELECT id FROM reminder_log WHERE chat_id = ? AND category = 'appt_snooze' "
            "AND ref_id = ? AND sent_at >= ?",
            (chat_id, appt_id, cutoff),
        ).fetchone() is not None


def _log_reminder(chat_id, appt_id, key):
    with db() as conn:
        conn.execute(
            "INSERT INTO reminder_log (chat_id, category, ref_id) VALUES (?, ?, ?)",
            (chat_id, key, appt_id),
        )


async def _send_appointment_reminder(context, chat_id, appt, days_away, working_tonight):
    from modules.appointments import CATEGORY_EMOJI, CATEGORIES
    cat = appt.get("category") or "other"
    cat_emoji = CATEGORY_EMOJI.get(cat, "📋")
    cat_label = CATEGORIES.get(cat, cat)
    event_date = date.fromisoformat(appt["event_date"])

    if days_away == 0:
        header, date_label = "🚨 TODAY", f"TODAY ({event_date.strftime('%b %d')})"
    elif days_away == 1:
        header, date_label = "🚨 APPOINTMENT REMINDER", f"tomorrow ({event_date.strftime('%b %d')})"
    else:
        header, date_label = "📅 APPOINTMENT REMINDER", f"in {days_away} days ({event_date.strftime('%b %d')})"

    lines = [header, "", f"📅 {appt['title']}",
             f"   {cat_emoji} {cat_label.split(' ', 1)[-1] if ' ' in cat_label else cat_label} — {date_label}"]

    if working_tonight and days_away <= 1:
        lines += ["", "⚠️ You're working tonight. Handle this before your shift or set time tomorrow."]

    if days_away == 0:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Done", callback_data=f"appts:remind_done:{appt['id']}"),
            InlineKeyboardButton("⏰ Snooze 2hrs", callback_data=f"appts:snooze2h:{appt['id']}"),
        ]])
    else:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Done", callback_data=f"appts:remind_done:{appt['id']}"),
             InlineKeyboardButton("⏰ Remind Later", callback_data=f"appts:remind_later:{appt['id']}")],
            [InlineKeyboardButton("📅 View Details", callback_data=f"appts:detail:{appt['id']}")],
        ])

    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), reply_markup=kb)


async def _send_followup_reminder(context, chat_id, appt):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Done", callback_data=f"appts:remind_done:{appt['id']}"),
        InlineKeyboardButton("⏰ Snooze 2hrs", callback_data=f"appts:snooze2h:{appt['id']}"),
    ]])
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🚨 Did you handle this?\n\n📅 {appt['title']}\n   Scheduled for today",
        reply_markup=kb,
    )



