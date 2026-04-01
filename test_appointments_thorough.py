"""
Thorough appointment tests for Butler Bot.
Covers:
1. Date parser — real human input with ordinals, abbreviations, slashes
2. Data integrity — appointment lands in correct table with correct fields
3. Reminder logic — priority-based reminders, deduplication, done suppression

Run: python3 test_appointments_thorough.py
"""

import asyncio
import os
import sys
import logging
import sqlite3
from datetime import date, timedelta, datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Set env before importing bot
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token_for_testing"
os.environ["DATABASE_PATH"] = "test_appts_thorough.db"

# Remove old test DB
if os.path.exists("test_appts_thorough.db"):
    os.remove("test_appts_thorough.db")

from config import DATABASE_PATH
from database import init_db, db, ensure_user
from helpers import today

# Module imports
from modules.appointments import (
    appts_callback, handle_appt_text,
    _parse_date_loosely, _parse_time_loosely,
    CATEGORY_EMOJI, CATEGORY_DEFAULT_PRIORITY, PRIORITY_LABELS, PRIORITY_REMINDERS,
)
from modules.scheduler import (
    appointment_reminder_check,
    _already_sent, _log_reminder, _recently_snoozed,
)
from bot import button_router, text_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("test_appts")

CHAT_ID = 88888
results = []
errors = []


def make_query(data, chat_id=CHAT_ID):
    """Create a mock CallbackQuery."""
    query = AsyncMock()
    query.data = data
    query.from_user = MagicMock()
    query.from_user.id = chat_id
    query.message = MagicMock()
    query.message.chat_id = chat_id
    query.message.chat = MagicMock()
    query.message.chat.id = chat_id
    query.message.reply_text = AsyncMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    return query


def make_update(data=None, text=None, chat_id=CHAT_ID):
    """Create a mock Update."""
    update = MagicMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user = MagicMock()
    update.effective_user.first_name = "TestUser"

    if data is not None:
        query = make_query(data, chat_id)
        update.callback_query = query
        update.message = None
    else:
        update.callback_query = None
        update.message = MagicMock()
        update.message.text = text or ""
        update.message.chat_id = chat_id
        update.message.chat = MagicMock()
        update.message.chat.id = chat_id
        update.message.reply_text = AsyncMock()

    return update


def make_context():
    """Create a mock context."""
    context = MagicMock()
    context.user_data = {}
    return context


async def run_callback(data, context=None, chat_id=CHAT_ID):
    """Simulate pressing a button."""
    ctx = context or make_context()
    update = make_update(data=data, chat_id=chat_id)
    try:
        await button_router(update, ctx)
        return update, ctx
    except Exception as e:
        errors.append(f"CALLBACK {data}: {e}")
        logger.error(f"❌ CALLBACK {data}: {e}", exc_info=True)
        return update, ctx


async def run_text(text, context, chat_id=CHAT_ID):
    """Simulate typing text."""
    update = make_update(text=text, chat_id=chat_id)
    try:
        await text_router(update, context)
        return update, context
    except Exception as e:
        errors.append(f"TEXT '{text}': {e}")
        logger.error(f"❌ TEXT '{text}': {e}", exc_info=True)
        return update, context


def check(label, condition):
    """Check a test condition."""
    status = "✅" if condition else "❌"
    results.append((label, condition))
    if not condition:
        errors.append(f"FAILED: {label}")
    logger.info(f"  {status} {label}")


# ── 1. DATE PARSER TESTS ──

async def test_date_parser():
    """Test _parse_date_loosely with real human input."""
    logger.info("\n═══ DATE PARSER TESTS ═══")
    current_year = datetime.now().year

    # "march 29th 2026" → 2026-03-29
    check("march 29th 2026", _parse_date_loosely("march 29th 2026") == "2026-03-29")

    # "March 29th" → current year march 29
    check("March 29th (no year)", _parse_date_loosely("March 29th") == f"{current_year}-03-29")

    # "march 29" → current year march 29
    check("march 29", _parse_date_loosely("march 29") == f"{current_year}-03-29")

    # "jan 1st 2027" → 2027-01-01
    check("jan 1st 2027", _parse_date_loosely("jan 1st 2027") == "2027-01-01")

    # "february 2nd" → current year feb 2
    check("february 2nd", _parse_date_loosely("february 2nd") == f"{current_year}-02-02")

    # "dec 3rd 2026" → 2026-12-03
    check("dec 3rd 2026", _parse_date_loosely("dec 3rd 2026") == "2026-12-03")

    # "April 15th, 2026" → 2026-04-15 (with comma)
    check("April 15th, 2026 (comma)", _parse_date_loosely("April 15th, 2026") == "2026-04-15")

    # "3/29/2026" → 2026-03-29
    check("3/29/2026 (slash)", _parse_date_loosely("3/29/2026") == "2026-03-29")

    # "3/29" → current year march 29
    check("3/29 (no year)", _parse_date_loosely("3/29") == f"{current_year}-03-29")

    # "2026-03-29" → 2026-03-29 (ISO)
    check("2026-03-29 (ISO)", _parse_date_loosely("2026-03-29") == "2026-03-29")

    # "29th of march 2026" → 2026-03-29 (reversed order)
    check("29th of march 2026", _parse_date_loosely("29th of march 2026") == "2026-03-29")


# ── 2. DATA INTEGRITY TESTS ──

async def test_data_integrity():
    """Test that appointments land in the correct table with correct fields."""
    logger.info("\n═══ DATA INTEGRITY TESTS ═══")
    ctx = make_context()

    # Full flow: Title → Category → Date → Time → Notes → Priority → Save
    # Step 1: Start add flow
    update, ctx = await run_callback("appts:add", ctx)
    check("add sets awaiting title", ctx.user_data.get("awaiting") == "appt_title")

    # Step 2: Type title
    await run_text("Dentist Cleaning", ctx)
    check("title stored in user_data", ctx.user_data.get("appt_title") == "Dentist Cleaning")
    check("after title, awaiting is None (category picker shown)", ctx.user_data.get("awaiting") is None)

    # Step 3: Pick category
    update, ctx = await run_callback("appts:category:medical", ctx)
    check("category stored", ctx.user_data.get("appt_category") == "medical")
    check("after category, awaiting date", ctx.user_data.get("awaiting") == "appt_date")

    # Step 4: Type date
    await run_text("April 15 2026", ctx)
    check("date stored", ctx.user_data.get("appt_date") == "2026-04-15")
    check("after date, awaiting time", ctx.user_data.get("awaiting") == "appt_time")

    # Step 5: Type time
    await run_text("2pm", ctx)
    check("after time, awaiting notes", ctx.user_data.get("awaiting") == "appt_notes")

    # Step 6: Type notes
    await run_text("Dr. Smith, bring insurance card", ctx)
    # Should now be at priority picker
    check("after notes, awaiting is None (priority picker)", ctx.user_data.get("awaiting") is None)

    # Step 7: Accept default priority
    update, ctx = await run_callback("appts:priority_ok", ctx)

    # Verify appointment is in the appointments table (NOT notes)
    with db() as conn:
        appt = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND title = 'Dentist Cleaning'",
            (CHAT_ID,)
        ).fetchone()
        # Make sure it's NOT in notes table
        note = conn.execute(
            "SELECT * FROM notes WHERE chat_id = ? AND content LIKE '%Dentist%'",
            (CHAT_ID,)
        ).fetchone()

    check("appointment in appointments table", appt is not None)
    check("appointment NOT in notes table", note is None)

    if appt:
        check("category saved correctly", appt["category"] == "medical")
        check("priority saved correctly (medical=3)", appt["priority"] == 3)
        check("reminder_level is smart", appt["reminder_level"] == "smart")
        check("date saved in ISO format", appt["event_date"] == "2026-04-15")
        check("time saved correctly", appt["event_time"] == "14:00")
        check("notes saved correctly", "Dr. Smith" in (appt["notes"] or ""))
        check("done defaults to 0", appt["done"] == 0)

    # Test with "no reminders" priority
    ctx2 = make_context()
    update, ctx2 = await run_callback("appts:add", ctx2)
    await run_text("Paul's Birthday Party", ctx2)
    update, ctx2 = await run_callback("appts:category:social", ctx2)
    await run_text("April 20 2026", ctx2)
    # Skip time
    update2 = make_update(data="appts:skip_time")
    ctx2.user_data["appt_title"] = ctx2.user_data.get("appt_title", "Paul's Birthday Party")
    ctx2.user_data["appt_date"] = ctx2.user_data.get("appt_date", "2026-04-20")
    await appts_callback(update2, ctx2)
    # Skip notes — goes to priority picker
    update3 = make_update(data="appts:skip_notes")
    ctx2.user_data["appt_title"] = ctx2.user_data.get("appt_title", "Paul's Birthday Party")
    ctx2.user_data["appt_date"] = ctx2.user_data.get("appt_date", "2026-04-20")
    ctx2.user_data["appt_time"] = ctx2.user_data.get("appt_time")
    await appts_callback(update3, ctx2)
    # Choose no reminders
    update4, ctx2 = await run_callback("appts:priority_none", ctx2)

    with db() as conn:
        appt2 = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND title = ?",
            (CHAT_ID, "Paul's Birthday Party")
        ).fetchone()
    check("no-reminder appointment saved", appt2 is not None)
    if appt2:
        check("category is social", appt2["category"] == "social")
        check("priority is 0 (none)", appt2["priority"] == 0)
        check("reminder_level is none", appt2["reminder_level"] == "none")
        check("time is NULL (skipped)", appt2["event_time"] is None)


async def test_category_edit():
    """Test editing category and priority via buttons."""
    logger.info("\n═══ CATEGORY & PRIORITY EDIT TESTS ═══")
    ctx = make_context()

    # Get an existing appointment
    with db() as conn:
        appt = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? LIMIT 1",
            (CHAT_ID,)
        ).fetchone()

    if not appt:
        check("need an appointment for edit test", False)
        return

    aid = appt["id"]

    # Edit category to financial
    update, ctx = await run_callback(f"appts:editcategory:{aid}", ctx)
    check("category picker shown", update.callback_query.edit_message_text.called)

    update, ctx = await run_callback(f"appts:setcategory:{aid}:financial", ctx)
    with db() as conn:
        a = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
    check("category changed to financial", a and a["category"] == "financial")

    # Edit priority to critical
    update, ctx = await run_callback(f"appts:editpriority:{aid}", ctx)
    check("priority picker shown", update.callback_query.edit_message_text.called)

    update, ctx = await run_callback(f"appts:setpriority:{aid}:4", ctx)
    with db() as conn:
        a = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
    check("priority changed to 4 (critical)", a and a["priority"] == 4)
    check("reminder_level set to smart", a and a["reminder_level"] == "smart")

    # Set priority to 0 (none)
    update, ctx = await run_callback(f"appts:setpriority:{aid}:0", ctx)
    with db() as conn:
        a = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
    check("priority changed to 0 (none)", a and a["priority"] == 0)
    check("reminder_level set to none", a and a["reminder_level"] == "none")


# ── 3. REMINDER LOGIC TESTS ──

async def test_reminder_logic():
    """Test the reminder engine logic."""
    logger.info("\n═══ REMINDER LOGIC TESTS ═══")
    d = today()

    # Clean up any test data
    with db() as conn:
        conn.execute("DELETE FROM appointments WHERE chat_id = ? AND title LIKE 'ReminderTest%'", (CHAT_ID,))
        conn.execute("DELETE FROM reminder_log WHERE chat_id = ?", (CHAT_ID,))

    # Test: Priority 0 → no reminders fire
    with db() as conn:
        conn.execute(
            "INSERT INTO appointments (chat_id, title, event_date, priority, reminder_level, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (CHAT_ID, "ReminderTest_None", (d + timedelta(days=1)).isoformat(), 0, "none", "other"),
        )

    context = MagicMock()
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()

    await appointment_reminder_check(context)
    # Priority 0 should NOT trigger any message
    calls = context.bot.send_message.call_args_list
    none_calls = [c for c in calls if "ReminderTest_None" in str(c)]
    check("priority 0 → no reminders", len(none_calls) == 0)

    # Test: Priority 2, 1 day before → reminder fires
    context.bot.send_message.reset_mock()
    with db() as conn:
        conn.execute("DELETE FROM reminder_log WHERE chat_id = ?", (CHAT_ID,))
        conn.execute(
            "INSERT INTO appointments (chat_id, title, event_date, priority, reminder_level, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (CHAT_ID, "ReminderTest_Moderate", (d + timedelta(days=1)).isoformat(), 2, "smart", "medical"),
        )

    await appointment_reminder_check(context)
    calls = context.bot.send_message.call_args_list
    moderate_calls = [c for c in calls if "ReminderTest_Moderate" in str(c)]
    check("priority 2, 1 day before → reminder fires", len(moderate_calls) > 0)

    # Test: Priority 4, 7 days before → reminder fires
    context.bot.send_message.reset_mock()
    with db() as conn:
        conn.execute("DELETE FROM reminder_log WHERE chat_id = ?", (CHAT_ID,))
        conn.execute(
            "INSERT INTO appointments (chat_id, title, event_date, priority, reminder_level, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (CHAT_ID, "ReminderTest_Critical", (d + timedelta(days=7)).isoformat(), 4, "smart", "financial"),
        )

    await appointment_reminder_check(context)
    calls = context.bot.send_message.call_args_list
    critical_calls = [c for c in calls if "ReminderTest_Critical" in str(c)]
    check("priority 4, 7 days before → reminder fires", len(critical_calls) > 0)

    # Test: Already-sent reminder → doesn't fire again
    context.bot.send_message.reset_mock()
    # The previous call already logged the reminder, so calling again shouldn't re-send
    await appointment_reminder_check(context)
    calls = context.bot.send_message.call_args_list
    critical_calls_2 = [c for c in calls if "ReminderTest_Critical" in str(c)]
    check("already-sent reminder doesn't re-fire", len(critical_calls_2) == 0)

    # Test: Appointment marked done → no more reminders
    context.bot.send_message.reset_mock()
    with db() as conn:
        conn.execute("DELETE FROM reminder_log WHERE chat_id = ?", (CHAT_ID,))
        conn.execute(
            "UPDATE appointments SET done = 1 WHERE chat_id = ? AND title = 'ReminderTest_Critical'",
            (CHAT_ID,),
        )

    await appointment_reminder_check(context)
    calls = context.bot.send_message.call_args_list
    done_calls = [c for c in calls if "ReminderTest_Critical" in str(c)]
    check("done appointment → no reminders", len(done_calls) == 0)


async def test_reminder_log_dedup():
    """Test reminder_log deduplication and snooze."""
    logger.info("\n═══ REMINDER LOG DEDUP TESTS ═══")
    d = today()

    with db() as conn:
        conn.execute("DELETE FROM reminder_log WHERE chat_id = ?", (CHAT_ID,))

    # Test _already_sent
    check("not sent yet → False", not _already_sent(CHAT_ID, 999, "appt_1d", d))

    # Log a reminder
    _log_reminder(CHAT_ID, 999, "appt_1d")
    check("after logging → True", _already_sent(CHAT_ID, 999, "appt_1d", d))

    # Different key → still False
    check("different key → False", not _already_sent(CHAT_ID, 999, "appt_3d", d))

    # Test snooze
    check("not snoozed → False", not _recently_snoozed(CHAT_ID, 998))
    with db() as conn:
        conn.execute(
            "INSERT INTO reminder_log (chat_id, category, ref_id) VALUES (?, ?, ?)",
            (CHAT_ID, "appt_snooze", 998),
        )
    check("after snooze → True", _recently_snoozed(CHAT_ID, 998))


async def test_smart_defaults():
    """Test category → priority smart defaults."""
    logger.info("\n═══ SMART DEFAULTS TESTS ═══")

    check("medical → priority 3", CATEGORY_DEFAULT_PRIORITY["medical"] == 3)
    check("car_admin → priority 2", CATEGORY_DEFAULT_PRIORITY["car_admin"] == 2)
    check("credential → priority 4", CATEGORY_DEFAULT_PRIORITY["credential"] == 4)
    check("financial → priority 4", CATEGORY_DEFAULT_PRIORITY["financial"] == 4)
    check("social → priority 1", CATEGORY_DEFAULT_PRIORITY["social"] == 1)
    check("other → priority 2", CATEGORY_DEFAULT_PRIORITY["other"] == 2)

    # Verify reminder thresholds
    check("priority 0 → no thresholds", PRIORITY_REMINDERS[0] == [])
    check("priority 1 → [1]", PRIORITY_REMINDERS[1] == [1])
    check("priority 2 → [1, 0]", PRIORITY_REMINDERS[2] == [1, 0])
    check("priority 3 → [3, 1, 0]", PRIORITY_REMINDERS[3] == [3, 1, 0])
    check("priority 4 → [7, 3, 1, 0]", PRIORITY_REMINDERS[4] == [7, 3, 1, 0])


async def test_callback_data_size():
    """Verify all callback data patterns stay under 64 bytes."""
    logger.info("\n═══ CALLBACK DATA SIZE TESTS ═══")

    # Test with largest reasonable appointment ID (6 digits)
    aid = 999999
    patterns = [
        f"appts:detail:{aid}",
        f"appts:done:{aid}",
        f"appts:undone:{aid}",
        f"appts:delete:{aid}",
        f"appts:confirm_delete:{aid}",
        f"appts:editfield:{aid}:title",
        f"appts:editfield:{aid}:event_date",
        f"appts:editfield:{aid}:event_time",
        f"appts:editfield:{aid}:notes",
        f"appts:editcategory:{aid}",
        f"appts:editpriority:{aid}",
        f"appts:setcategory:{aid}:credential",
        f"appts:setcategory:{aid}:car_admin",
        f"appts:setpriority:{aid}:4",
        f"appts:remind_done:{aid}",
        f"appts:remind_later:{aid}",
        f"appts:remind_view:{aid}",
        f"appts:snooze2h:{aid}",
        "appts:category:medical",
        "appts:category:car_admin",
        "appts:category:credential",
        "appts:category:financial",
        "appts:priority_ok",
        "appts:priority_none",
        "appts:priority_up",
        "appts:priority_down",
    ]

    all_ok = True
    for pattern in patterns:
        size = len(pattern.encode("utf-8"))
        if size > 64:
            check(f"callback '{pattern}' is {size} bytes (>64!)", False)
            all_ok = False
    check("all callback data under 64 bytes", all_ok)


async def test_existing_appts_still_work():
    """Test that appointments without new columns still work (backward compat)."""
    logger.info("\n═══ BACKWARD COMPATIBILITY TESTS ═══")

    # Insert an appointment without new columns (simulating old data)
    with db() as conn:
        conn.execute(
            "INSERT INTO appointments (chat_id, title, event_date, event_time, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (CHAT_ID, "OldStyleAppt", "2026-05-01", "09:00", "Old notes"),
        )
        appt = conn.execute(
            "SELECT * FROM appointments WHERE chat_id = ? AND title = 'OldStyleAppt'",
            (CHAT_ID,)
        ).fetchone()

    check("old-style appointment readable", appt is not None)
    if appt:
        # Default values should be applied
        try:
            cat = appt["category"]
            check("default category is 'other'", cat == "other")
        except (IndexError, KeyError):
            check("category column exists", False)

        try:
            prio = appt["priority"]
            check("default priority is 2", prio == 2)
        except (IndexError, KeyError):
            check("priority column exists", False)

        try:
            rl = appt["reminder_level"]
            check("default reminder_level is 'smart'", rl == "smart")
        except (IndexError, KeyError):
            check("reminder_level column exists", False)

        # Detail view should work
        ctx = make_context()
        update, ctx = await run_callback(f"appts:detail:{appt['id']}", ctx)
        text = update.callback_query.edit_message_text.call_args[0][0]
        check("old appt detail shows title", "OldStyleAppt" in text)
        check("old appt detail shows category", "Other" in text or "other" in text.lower())


# ── MAIN ──

async def main():
    """Run all tests."""
    init_db()
    ensure_user(CHAT_ID, "TestUser")

    # Mark user as onboarded for reminder tests
    with db() as conn:
        conn.execute("UPDATE users SET onboarded = 1 WHERE chat_id = ?", (CHAT_ID,))

    await test_date_parser()
    await test_data_integrity()
    await test_category_edit()
    await test_reminder_logic()
    await test_reminder_log_dedup()
    await test_smart_defaults()
    await test_callback_data_size()
    await test_existing_appts_still_work()

    # Summary
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    total = len(results)

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'='*60}")

    if errors:
        print("\n❌ FAILURES:")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)
    else:
        print("\n✅ ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
