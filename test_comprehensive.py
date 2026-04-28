"""
Comprehensive test script for Butler Bot.
Simulates the full Telegram API interaction by mocking telegram objects
and running every callback/text handler with real DB operations.

Tests every button and every flow:
1. /start onboarding (full persona)
2. Today view
3. Week view + navigation (prev/next multiple times)
4. Bills: add, detail, edit fields, mark paid/unpaid, delete
5. Partners: add, add dates, schedule, edit fields, delete
6. Car: add (typed + preset), detail, edit, mark done, delete
7. Credentials: add, detail, edit all fields, mark renewed, delete
8. Meds: add, detail, mark taken/untaken, edit, delete
9. Notes: add (general + attached), detail, delete
10. Appointments: add (full flow), detail, edit, mark done, delete
11. Settings: view, change shift type, change week days, override
12. Capture/Inbox menu
13. Field editor for every module
14. Delete everything and re-run
"""

import asyncio
import json
import os
import sys
import logging
import sqlite3
from datetime import date, timedelta, datetime
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
from types import SimpleNamespace

# Set env before importing bot
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token_for_testing"
os.environ["DATABASE_PATH"] = "test_butler.db"

# Remove old test DB
if os.path.exists("test_butler.db"):
    os.remove("test_butler.db")

from config import DATABASE_PATH
from database import init_db, db, ensure_user, get_user, update_user
from helpers import today, ascii_week_calendar

# Modules
from modules.onboarding import onboard_callback, handle_onboard_text, start_command
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
from bot import button_router, handle_menu, handle_capture, handle_settings, text_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("test")

CHAT_ID = 99999  # Test user
TEST_NAME = "TestBot"

# Track all results
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
    update.effective_user.first_name = TEST_NAME

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


async def test_onboarding():
    """Test complete onboarding flow."""
    logger.info("\n═══ ONBOARDING ═══")
    ctx = make_context()

    # /start
    update = make_update(text="/start")
    await start_command(update, ctx)
    check("start_command responds", update.message.reply_text.called)

    # "Let's Set Up" button
    update, ctx = await run_callback("onboard:start", ctx)
    _u = get_user(CHAT_ID); check("onboard:start sets step=name", _u and _u["onboard_step"] == "name")

    # Type name
    update, ctx = await run_text("Testie McTestFace", ctx)
    user = get_user(CHAT_ID)
    check("name saved to DB", user and user["display_name"] == "Testie McTestFace")

    # Pick shift type
    update, ctx = await run_callback("onboard:shift:7p-7a", ctx)
    user = get_user(CHAT_ID)
    ob_data = json.loads(user["onboard_data"] or "{}")
    check("shift type saved", ob_data.get("shift_type") == "7p-7a")

    # Pick week 1 days: Mon, Tue, Sat
    await run_callback("onboard:day:0", ctx)  # Mon
    await run_callback("onboard:day:1", ctx)  # Tue
    await run_callback("onboard:day:5", ctx)  # Sat
    await run_callback("onboard:days_done", ctx)  # stores weeks[0], asks "add week 2?"

    user = get_user(CHAT_ID)
    ob_data = json.loads(user["onboard_data"] or "{}")
    # New state machine: week 1 is in ob_data["weeks"][0], not ob_data["week1_days"]
    check("week1 days saved", ob_data.get("weeks", [[]])[0] == [0, 1, 5])

    # Say yes to week 2 (new callback name: add_week)
    await run_callback("onboard:add_week:yes", ctx)

    # Pick week 2: Sun, Wed, Thu
    await run_callback("onboard:day:6", ctx)  # Sun
    await run_callback("onboard:day:2", ctx)  # Wed
    await run_callback("onboard:day:3", ctx)  # Thu
    await run_callback("onboard:days_done", ctx)  # stores weeks[1], asks "add week 3?"
    await run_callback("onboard:add_week:no", ctx)  # done — saves shift to DB

    # Check shift saved to DB
    with db() as conn:
        shift = conn.execute("SELECT * FROM shifts WHERE chat_id = ?", (CHAT_ID,)).fetchone()
    check("shift saved to DB", shift is not None)
    if shift:
        check("week1_days in DB", json.loads(shift["week1_days"]) == [0, 1, 5])
        check("week2_days in DB", json.loads(shift["week2_days"]) == [2, 3, 6])

    # Partners: Yes, add "Alex"
    await run_callback("onboard:partners_intro", ctx)
    await run_callback("onboard:add_partners:yes", ctx)
    _u2 = get_user(CHAT_ID); check("awaiting partner name (DB step)", _u2 and _u2["onboard_step"] == "partner_name")
    await run_text("Alex", ctx)
    with db() as conn:
        partners = conn.execute("SELECT * FROM partners WHERE chat_id = ?", (CHAT_ID,)).fetchall()
    check("partner Alex saved", len(partners) >= 1 and any(p["name"] == "Alex" for p in partners))

    # Add another partner: "Sam"
    await run_callback("onboard:another_partner:yes", ctx)
    await run_text("Sam", ctx)
    with db() as conn:
        partners = conn.execute("SELECT * FROM partners WHERE chat_id = ?", (CHAT_ID,)).fetchall()
    check("partner Sam saved", len(partners) >= 2)

    # Done with partners
    await run_callback("onboard:another_partner:no", ctx)

    # Bills: Yes, add "Rent" $1200
    await run_callback("onboard:bills_intro", ctx)
    await run_callback("onboard:add_bills:yes", ctx)
    await run_text("Rent", ctx)
    await run_text("1200", ctx)
    await run_callback("onboard:bill_freq:monthly", ctx)  # frequency picker (new step)
    await run_callback("onboard:bill_due_day:1", ctx)     # due day picker (new step)
    with db() as conn:
        bills = conn.execute("SELECT * FROM bills WHERE chat_id = ?", (CHAT_ID,)).fetchall()
    check("bill Rent saved", len(bills) >= 1 and any(b["name"] == "Rent" for b in bills))

    # Add another bill
    await run_callback("onboard:add_bills:yes", ctx)  # still in bill_name step
    await run_text("Electric", ctx)
    await run_text("150", ctx)
    await run_callback("onboard:bill_freq:monthly", ctx)
    await run_callback("onboard:bill_due_day:15", ctx)

    # Done with bills — go to car section
    await run_callback("onboard:add_bills:no", ctx)

    # Car: Yes, add inspection (uses button type + button date picker)
    await run_callback("onboard:car_intro", ctx)
    await run_callback("onboard:add_car:yes", ctx)
    await run_callback("onboard:car_type:inspection", ctx)  # pick type via button
    # Date picker: month then day
    await run_callback("onboard:ob_date:car:month:6:2026", ctx)
    await run_callback("onboard:ob_date:car:day:2026-06-15", ctx)
    with db() as conn:
        cars = conn.execute("SELECT * FROM car_events WHERE chat_id = ?", (CHAT_ID,)).fetchall()
    check("car event saved", len(cars) >= 1)

    # Done with car
    await run_callback("onboard:add_car:no", ctx)

    # Credentials: Yes (also uses button date picker)
    await run_callback("onboard:creds_intro", ctx)
    await run_callback("onboard:add_creds:yes", ctx)
    await run_text("RRT License", ctx)
    # Date picker for expiry
    await run_callback("onboard:ob_date:cred:month:6:2027", ctx)
    await run_callback("onboard:ob_date:cred:day:2027-06-01", ctx)
    with db() as conn:
        creds = conn.execute("SELECT * FROM credentials WHERE chat_id = ?", (CHAT_ID,)).fetchall()
    check("credential saved", len(creds) >= 1)

    # Done with creds
    await run_callback("onboard:add_creds:no", ctx)

    # Meds: Yes
    await run_callback("onboard:meds_intro", ctx)
    await run_callback("onboard:add_meds:yes", ctx)
    await run_text("Adderall", ctx)
    with db() as conn:
        meds = conn.execute("SELECT * FROM medications WHERE chat_id = ?", (CHAT_ID,)).fetchall()
    check("medication saved", len(meds) >= 1)

    # Done with meds = finish
    await run_callback("onboard:another_med:no", ctx)

    user = get_user(CHAT_ID)
    check("user marked onboarded", user and user["onboarded"] == 1)

    return ctx


async def test_today_view():
    """Test Today/Tonight view."""
    logger.info("\n═══ TODAY VIEW ═══")
    update, ctx = await run_callback("today:view")
    query = update.callback_query
    check("today:view called edit_message_text", query.edit_message_text.called)
    text = query.edit_message_text.call_args[0][0] if query.edit_message_text.call_args else ""
    check("today view shows greeting", "Testie McTestFace" in text or "TestBot" in text or "good" in text.lower() or "night" in text.lower() or "late" in text.lower())
    check("today view shows date", today().strftime("%A") in text or today().strftime("%B") in text)


async def test_week_view():
    """Test Week View with navigation."""
    logger.info("\n═══ WEEK VIEW ═══")

    # Initial view
    update, ctx = await run_callback("week:view")
    query = update.callback_query
    check("week:view responds", query.edit_message_text.called)
    text = query.edit_message_text.call_args[0][0] if query.edit_message_text.call_args else ""
    check("week view has calendar box", "┌" in text and "┘" in text)

    # Check navigation buttons have offset
    kb = query.edit_message_text.call_args[1].get("reply_markup") if query.edit_message_text.call_args[1] else None
    if kb:
        buttons = []
        for row in kb.inline_keyboard:
            for btn in row:
                buttons.append(btn.callback_data)
        check("nav buttons include offset", "week:prev:0" in buttons and "week:next:0" in buttons)
        check("no 'This Week' at offset 0", "week:view:0" not in buttons)

    # Navigate next
    update2, ctx2 = await run_callback("week:next:0")
    query2 = update2.callback_query
    text2 = query2.edit_message_text.call_args[0][0] if query2.edit_message_text.call_args else ""
    check("next week shows different week", text2 != "" and text2 != text)

    # Check buttons now have offset 7
    kb2 = query2.edit_message_text.call_args[1].get("reply_markup") if query2.edit_message_text.call_args[1] else None
    if kb2:
        buttons2 = []
        for row in kb2.inline_keyboard:
            for btn in row:
                buttons2.append(btn.callback_data)
        check("next week buttons have offset 7", "week:prev:7" in buttons2 and "week:next:7" in buttons2)
        check("'This Week' shown at offset 7", "week:view:0" in buttons2)

    # Navigate next again (should be offset 14)
    update3, ctx3 = await run_callback("week:next:7")
    query3 = update3.callback_query
    kb3 = query3.edit_message_text.call_args[1].get("reply_markup") if query3.edit_message_text.call_args[1] else None
    if kb3:
        buttons3 = []
        for row in kb3.inline_keyboard:
            for btn in row:
                buttons3.append(btn.callback_data)
        check("2nd next has offset 14", "week:prev:14" in buttons3 and "week:next:14" in buttons3)

    # Navigate back twice
    update4, ctx4 = await run_callback("week:prev:14")  # offset 7
    update5, ctx5 = await run_callback("week:prev:7")   # offset 0

    # Go way forward (52 weeks = 1 year)
    current_offset = 0
    for i in range(52):
        current_offset += 7
    update_far, ctx_far = await run_callback(f"week:next:{current_offset - 7}")
    query_far = update_far.callback_query
    check("1 year forward works", query_far.edit_message_text.called)

    # Come back
    update_back, ctx_back = await run_callback(f"week:view:0")
    check("jump back to this week works", update_back.callback_query.edit_message_text.called)


async def test_bills_crud():
    """Test Bills: add, detail, edit, paid, delete."""
    logger.info("\n═══ BILLS ═══")
    ctx = make_context()

    # View bills
    update, ctx = await run_callback("bills:view", ctx)
    check("bills:view responds", update.callback_query.edit_message_text.called)

    # Add a new bill via module flow
    update, ctx = await run_callback("bills:add", ctx)
    check("bills:add sets awaiting", ctx.user_data.get("awaiting") == "bill_name")

    await run_text("Internet", ctx)
    check("after name, awaiting amount", ctx.user_data.get("awaiting") == "bill_amount")

    await run_text("89.99", ctx)
    check("after amount, awaiting due day", ctx.user_data.get("awaiting") == "bill_due_day")

    await run_text("15", ctx)

    with db() as conn:
        internet = conn.execute("SELECT * FROM bills WHERE chat_id = ? AND name = 'Internet'", (CHAT_ID,)).fetchone()
    check("Internet bill saved", internet is not None)
    check("Internet amount correct", internet and abs(internet["amount"] - 89.99) < 0.01)
    check("Internet due day correct", internet and internet["due_day"] == 15)

    # Detail view
    if internet:
        bill_id = internet["id"]
        update, ctx = await run_callback(f"bills:detail:{bill_id}", ctx)
        check("bill detail responds", update.callback_query.edit_message_text.called)
        text = update.callback_query.edit_message_text.call_args[0][0]
        check("detail shows name", "Internet" in text)
        check("detail shows amount", "$89.99" in text)

        # Mark paid
        update, ctx = await run_callback(f"bills:paid:{bill_id}", ctx)
        with db() as conn:
            b = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        check("bill marked paid", b and b["paid_this_cycle"] == 1)

        # Mark unpaid
        update, ctx = await run_callback(f"bills:unpaid:{bill_id}", ctx)
        with db() as conn:
            b = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        check("bill marked unpaid", b and b["paid_this_cycle"] == 0)

        # Edit field: name
        update, ctx = await run_callback(f"bills:editfield:{bill_id}:name", ctx)
        check("editfield sets awaiting", ctx.user_data.get("awaiting") == "field_edit")
        await run_text("Internet (Xfinity)", ctx)
        with db() as conn:
            b = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        check("name edited", b and b["name"] == "Internet (Xfinity)")

        # Edit field: amount
        update, ctx = await run_callback(f"bills:editfield:{bill_id}:amount", ctx)
        await run_text("95.50", ctx)
        with db() as conn:
            b = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        check("amount edited", b and abs(b["amount"] - 95.50) < 0.01)

        # Edit field: due_day
        update, ctx = await run_callback(f"bills:editfield:{bill_id}:due_day", ctx)
        await run_text("20", ctx)
        with db() as conn:
            b = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        check("due_day edited", b and b["due_day"] == 20)

        # Edit field: frequency
        update, ctx = await run_callback(f"bills:editfield:{bill_id}:frequency", ctx)
        await run_text("biweekly", ctx)
        with db() as conn:
            b = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        check("frequency edited", b and b["frequency"] == "biweekly")

        # Edit field: account_user
        update, ctx = await run_callback(f"bills:editfield:{bill_id}:account_user", ctx)
        await run_text("user@xfinity.com", ctx)
        with db() as conn:
            b = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        check("account_user edited", b and b["account_user"] == "user@xfinity.com")

        # Payday summary
        update, ctx = await run_callback("bills:payday", ctx)
        check("payday summary responds", update.callback_query.edit_message_text.called)

        # Delete
        update, ctx = await run_callback(f"bills:delete:{bill_id}", ctx)
        check("delete confirmation shown", update.callback_query.edit_message_text.called)
        update, ctx = await run_callback(f"bills:confirm_delete:{bill_id}", ctx)
        with db() as conn:
            b = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        check("bill deleted", b is None)


async def test_partners_crud():
    """Test Partners: add, dates, schedule, edit, delete."""
    logger.info("\n═══ PARTNERS ═══")
    ctx = make_context()

    # View
    update, ctx = await run_callback("partners:view", ctx)
    check("partners:view responds", update.callback_query.edit_message_text.called)

    # Add partner
    update, ctx = await run_callback("partners:add", ctx)
    check("partners:add sets awaiting", ctx.user_data.get("awaiting") == "partner_name")
    await run_text("Jordan", ctx)
    with db() as conn:
        p = conn.execute("SELECT * FROM partners WHERE chat_id = ? AND name = 'Jordan'", (CHAT_ID,)).fetchone()
    check("partner Jordan saved", p is not None)

    if p:
        pid = p["id"]

        # Detail view
        update, ctx = await run_callback(f"partners:detail:{pid}", ctx)
        check("partner detail responds", update.callback_query.edit_message_text.called)

        # Add birthday
        update, ctx = await run_callback(f"partners:adddate:birthday:{pid}", ctx)
        check("birthday prompts for date", ctx.user_data.get("awaiting") == "partner_date_value")
        await run_text("07-15", ctx)
        with db() as conn:
            dates = conn.execute("SELECT * FROM partner_dates WHERE partner_id = ?", (pid,)).fetchall()
        check("birthday saved", len(dates) >= 1)

        # Add anniversary
        update, ctx = await run_callback(f"partners:adddate:anniversary:{pid}", ctx)
        await run_text("2024-02-14", ctx)
        with db() as conn:
            dates = conn.execute("SELECT * FROM partner_dates WHERE partner_id = ?", (pid,)).fetchall()
        check("anniversary saved", len(dates) >= 2)

        # Schedule date
        update, ctx = await run_callback(f"partners:schedule:{pid}", ctx)
        check("schedule shows free days", update.callback_query.edit_message_text.called)

        # Edit name
        update, ctx = await run_callback(f"partners:editfield:{pid}:name", ctx)
        check("edit name sets field_edit", ctx.user_data.get("awaiting") == "field_edit")
        await run_text("Jordan B", ctx)
        with db() as conn:
            p = conn.execute("SELECT * FROM partners WHERE id = ?", (pid,)).fetchone()
        check("partner name edited", p and p["name"] == "Jordan B")

        # Edit emoji
        update, ctx = await run_callback(f"partners:editfield:{pid}:emoji", ctx)
        await run_text("❤️", ctx)
        with db() as conn:
            p = conn.execute("SELECT * FROM partners WHERE id = ?", (pid,)).fetchone()
        check("partner emoji edited", p and p["emoji"] == "❤️")

        # Edit target dates
        update, ctx = await run_callback(f"partners:editfield:{pid}:target_dates_per_month", ctx)
        await run_text("4", ctx)
        with db() as conn:
            p = conn.execute("SELECT * FROM partners WHERE id = ?", (pid,)).fetchone()
        check("target dates edited", p and p["target_dates_per_month"] == 4)

        # Delete
        update, ctx = await run_callback(f"partners:delete:{pid}", ctx)
        update, ctx = await run_callback(f"partners:confirm_delete:{pid}", ctx)
        with db() as conn:
            p = conn.execute("SELECT * FROM partners WHERE id = ?", (pid,)).fetchone()
        check("partner deleted", p is None)


async def test_car_crud():
    """Test Car module: add (preset + custom), detail, edit, done, delete."""
    logger.info("\n═══ CAR / ADMIN ═══")
    ctx = make_context()

    # View
    update, ctx = await run_callback("car:view", ctx)
    check("car:view responds", update.callback_query.edit_message_text.called)

    # Add via preset type
    update, ctx = await run_callback("car:add", ctx)
    check("car:add shows type picker", update.callback_query.edit_message_text.called)

    update, ctx = await run_callback("car:addtype:inspection", ctx)
    check("inspection sets awaiting date", ctx.user_data.get("awaiting") == "car_date")
    await run_text("2026-09-01", ctx)
    with db() as conn:
        cars = conn.execute("SELECT * FROM car_events WHERE chat_id = ? AND event_type = 'inspection'", (CHAT_ID,)).fetchall()
    check("inspection saved", len(cars) >= 1)

    # Add custom type
    update, ctx = await run_callback("car:add", ctx)
    update, ctx = await run_callback("car:addtype:custom", ctx)
    check("custom type awaiting desc", ctx.user_data.get("awaiting") == "car_desc")
    await run_text("Tire Rotation", ctx)
    check("after desc, awaiting date", ctx.user_data.get("awaiting") == "car_date")
    await run_text("2026-08-15", ctx)
    with db() as conn:
        cars = conn.execute("SELECT * FROM car_events WHERE chat_id = ? AND description = 'Tire Rotation'", (CHAT_ID,)).fetchall()
    check("custom car event saved", len(cars) >= 1)

    if cars:
        eid = cars[0]["id"]

        # Detail
        update, ctx = await run_callback(f"car:detail:{eid}", ctx)
        check("car detail responds", update.callback_query.edit_message_text.called)

        # Edit description
        update, ctx = await run_callback(f"car:editfield:{eid}:description", ctx)
        await run_text("Tire Rotation + Balance", ctx)
        with db() as conn:
            e = conn.execute("SELECT * FROM car_events WHERE id = ?", (eid,)).fetchone()
        check("car desc edited", e and e["description"] == "Tire Rotation + Balance")

        # Edit due date
        update, ctx = await run_callback(f"car:editfield:{eid}:due_date", ctx)
        await run_text("2026-09-15", ctx)
        with db() as conn:
            e = conn.execute("SELECT * FROM car_events WHERE id = ?", (eid,)).fetchone()
        check("car due_date edited", e and e["due_date"] == "2026-09-15")

        # Edit mileage
        update, ctx = await run_callback(f"car:editfield:{eid}:mileage", ctx)
        await run_text("45000", ctx)
        with db() as conn:
            e = conn.execute("SELECT * FROM car_events WHERE id = ?", (eid,)).fetchone()
        check("car mileage edited", e and e["mileage"] == 45000)

        # Mark done
        update, ctx = await run_callback(f"car:done:{eid}", ctx)
        with db() as conn:
            e = conn.execute("SELECT * FROM car_events WHERE id = ?", (eid,)).fetchone()
        check("car marked done", e and e["done"] == 1)

        # Reopen
        update, ctx = await run_callback(f"car:undone:{eid}", ctx)
        with db() as conn:
            e = conn.execute("SELECT * FROM car_events WHERE id = ?", (eid,)).fetchone()
        check("car reopened", e and e["done"] == 0)

        # Delete
        update, ctx = await run_callback(f"car:delete:{eid}", ctx)
        update, ctx = await run_callback(f"car:confirm_delete:{eid}", ctx)
        with db() as conn:
            e = conn.execute("SELECT * FROM car_events WHERE id = ?", (eid,)).fetchone()
        check("car event deleted", e is None)


async def test_credentials_crud():
    """Test Credentials: add, detail, all edit fields, renew, delete."""
    logger.info("\n═══ CREDENTIALS ═══")
    ctx = make_context()

    # View
    update, ctx = await run_callback("creds:view", ctx)
    check("creds:view responds", update.callback_query.edit_message_text.called)

    # Add
    update, ctx = await run_callback("creds:add", ctx)
    check("creds:add sets awaiting", ctx.user_data.get("awaiting") == "cred_name")
    await run_text("BLS Certification", ctx)
    await run_text("2027-12-01", ctx)

    with db() as conn:
        c = conn.execute("SELECT * FROM credentials WHERE chat_id = ? AND name = 'BLS Certification'", (CHAT_ID,)).fetchone()
    check("BLS credential saved", c is not None)

    if c:
        cid = c["id"]

        # Detail
        update, ctx = await run_callback(f"creds:detail:{cid}", ctx)
        check("cred detail responds", update.callback_query.edit_message_text.called)

        # Edit every field
        for field, value, expected_field, expected_val in [
            ("name", "BLS-CPR", "name", "BLS-CPR"),
            ("credential_num", "BLS-12345", "credential_num", "BLS-12345"),
            ("state", "PA", "state", "PA"),
            ("expiry_date", "2028-01-15", "expiry_date", "2028-01-15"),
            ("ceu_required", "30", "ceu_required", 30),
            ("ceu_completed", "12", "ceu_completed", 12),
            ("issuing_body", "AHA", "issuing_body", "AHA"),
            ("renewal_url", "https://aha.org/renew", "renewal_url", "https://aha.org/renew"),
        ]:
            update, ctx = await run_callback(f"creds:editfield:{cid}:{field}", ctx)
            await run_text(value, ctx)
            with db() as conn:
                c = conn.execute("SELECT * FROM credentials WHERE id = ?", (cid,)).fetchone()
            check(f"cred {field} edited", c and c[expected_field] == expected_val)

        # Mark renewed
        update, ctx = await run_callback(f"creds:renewed:{cid}", ctx)
        with db() as conn:
            c = conn.execute("SELECT * FROM credentials WHERE id = ?", (cid,)).fetchone()
        check("cred marked renewed", c and c["renewed"] == 1)

        # Delete
        update, ctx = await run_callback(f"creds:delete:{cid}", ctx)
        update, ctx = await run_callback(f"creds:confirm_delete:{cid}", ctx)
        with db() as conn:
            c = conn.execute("SELECT * FROM credentials WHERE id = ?", (cid,)).fetchone()
        check("cred deleted", c is None)


async def test_meds_crud():
    """Test Meds: add, detail, take, untake, edit fields, delete."""
    logger.info("\n═══ MEDICATIONS ═══")
    ctx = make_context()

    # View
    update, ctx = await run_callback("meds:view", ctx)
    check("meds:view responds", update.callback_query.edit_message_text.called)

    # Add
    update, ctx = await run_callback("meds:add", ctx)
    check("meds:add sets awaiting", ctx.user_data.get("awaiting") == "med_name")
    await run_text("Metformin", ctx)
    await run_text("500mg", ctx)

    with db() as conn:
        m = conn.execute("SELECT * FROM medications WHERE chat_id = ? AND name = 'Metformin'", (CHAT_ID,)).fetchone()
    check("Metformin saved", m is not None)
    check("Metformin dosage saved", m and m["dosage"] == "500mg")

    if m:
        mid = m["id"]

        # Detail
        update, ctx = await run_callback(f"meds:detail:{mid}", ctx)
        check("med detail responds", update.callback_query.edit_message_text.called)

        # Take
        update, ctx = await run_callback(f"meds:take:{mid}", ctx)
        with db() as conn:
            m = conn.execute("SELECT * FROM medications WHERE id = ?", (mid,)).fetchone()
        check("med marked taken", m and m["taken_today"] == 1)

        # Untake
        update, ctx = await run_callback(f"meds:untake:{mid}", ctx)
        with db() as conn:
            m = conn.execute("SELECT * FROM medications WHERE id = ?", (mid,)).fetchone()
        check("med unmarked", m and m["taken_today"] == 0)

        # All taken
        update, ctx = await run_callback("meds:all_taken", ctx)
        with db() as conn:
            untaken = conn.execute("SELECT COUNT(*) as c FROM medications WHERE chat_id = ? AND taken_today = 0", (CHAT_ID,)).fetchone()
        check("all meds marked taken", untaken and untaken["c"] == 0)

        # Edit name
        update, ctx = await run_callback(f"meds:editfield:{mid}:name", ctx)
        await run_text("Metformin XR", ctx)
        with db() as conn:
            m = conn.execute("SELECT * FROM medications WHERE id = ?", (mid,)).fetchone()
        check("med name edited", m and m["name"] == "Metformin XR")

        # Edit dosage
        update, ctx = await run_callback(f"meds:editfield:{mid}:dosage", ctx)
        await run_text("1000mg", ctx)
        with db() as conn:
            m = conn.execute("SELECT * FROM medications WHERE id = ?", (mid,)).fetchone()
        check("med dosage edited", m and m["dosage"] == "1000mg")

        # Edit frequency
        update, ctx = await run_callback(f"meds:editfield:{mid}:frequency", ctx)
        await run_text("twice daily", ctx)
        with db() as conn:
            m = conn.execute("SELECT * FROM medications WHERE id = ?", (mid,)).fetchone()
        check("med frequency edited", m and m["frequency"] == "twice daily")

        # Edit refill date
        update, ctx = await run_callback(f"meds:editfield:{mid}:refill_date", ctx)
        await run_text("2026-04-15", ctx)
        with db() as conn:
            m = conn.execute("SELECT * FROM medications WHERE id = ?", (mid,)).fetchone()
        check("med refill date edited", m and m["refill_date"] == "2026-04-15")

        # Delete
        update, ctx = await run_callback(f"meds:delete:{mid}", ctx)
        update, ctx = await run_callback(f"meds:confirm_delete:{mid}", ctx)
        with db() as conn:
            m = conn.execute("SELECT * FROM medications WHERE id = ?", (mid,)).fetchone()
        check("med deleted", m is None)


async def test_notes_crud():
    """Test Notes: add general, add attached, detail, delete."""
    logger.info("\n═══ NOTES ═══")
    ctx = make_context()

    # View (empty)
    update, ctx = await run_callback("notes:view", ctx)
    check("notes:view responds", update.callback_query.edit_message_text.called)

    # Add general note
    update, ctx = await run_callback("notes:add:general", ctx)
    check("notes:add sets awaiting", ctx.user_data.get("awaiting") == "note_content")
    await run_text("Remember to check work schedule", ctx)
    with db() as conn:
        notes = conn.execute("SELECT * FROM notes WHERE chat_id = ? AND category = 'general'", (CHAT_ID,)).fetchall()
    check("general note saved", len(notes) >= 1)

    # Add note attached to a bill
    with db() as conn:
        bill = conn.execute("SELECT id FROM bills WHERE chat_id = ? LIMIT 1", (CHAT_ID,)).fetchone()
    if bill:
        update, ctx = await run_callback(f"notes:add:bill:{bill['id']}", ctx)
        await run_text("Auto-pay is set up", ctx)
        with db() as conn:
            notes = conn.execute("SELECT * FROM notes WHERE chat_id = ? AND category = 'bill'", (CHAT_ID,)).fetchall()
        check("attached note saved", len(notes) >= 1)

    # View all notes
    update, ctx = await run_callback("notes:view", ctx)
    check("notes:view shows notes", update.callback_query.edit_message_text.called)

    # Detail and delete
    with db() as conn:
        note = conn.execute("SELECT * FROM notes WHERE chat_id = ? LIMIT 1", (CHAT_ID,)).fetchone()
    if note:
        nid = note["id"]
        update, ctx = await run_callback(f"notes:detail:{nid}", ctx)
        check("note detail responds", update.callback_query.edit_message_text.called)

        update, ctx = await run_callback(f"notes:delete:{nid}", ctx)
        with db() as conn:
            n = conn.execute("SELECT * FROM notes WHERE id = ?", (nid,)).fetchone()
        check("note deleted", n is None)


async def test_appointments_crud():
    """Test Appointments: full add flow, detail, edit, done, delete."""
    logger.info("\n═══ APPOINTMENTS ═══")
    ctx = make_context()

    # View
    update, ctx = await run_callback("appts:view", ctx)
    check("appts:view responds", update.callback_query.edit_message_text.called)

    # Add appointment - full flow (Title → Category → Date → Time → Notes → Priority → Save)
    update, ctx = await run_callback("appts:add", ctx)
    check("appts:add sets awaiting title", ctx.user_data.get("awaiting") == "appt_title")

    # Step 1: Title → shows category picker
    await run_text("Dentist Cleaning", ctx)
    check("after title, awaiting None (category picker)", ctx.user_data.get("awaiting") is None)

    # Step 2: Category → asks for date
    update, ctx = await run_callback("appts:category:medical", ctx)
    check("after category, awaiting date", ctx.user_data.get("awaiting") == "appt_date")

    # Step 3: Date
    await run_text("April 15 2026", ctx)
    check("date saved in user_data", ctx.user_data.get("appt_date") == "2026-04-15")
    check("after date, awaiting time", ctx.user_data.get("awaiting") == "appt_time")

    # Step 4: Time
    await run_text("2pm", ctx)
    check("after time, awaiting notes", ctx.user_data.get("awaiting") == "appt_notes")

    # Step 5: Notes → shows priority picker
    await run_text("Dr. Smith, bring insurance card", ctx)
    check("after notes, awaiting None (priority picker)", ctx.user_data.get("awaiting") is None)

    # Step 6: Accept default priority → saves
    update, ctx = await run_callback("appts:priority_ok", ctx)

    with db() as conn:
        appt = conn.execute("SELECT * FROM appointments WHERE chat_id = ? AND title = 'Dentist Cleaning'", (CHAT_ID,)).fetchone()
    check("appointment saved to DB", appt is not None)
    check("appointment date correct", appt and appt["event_date"] == "2026-04-15")
    check("appointment time correct", appt and appt["event_time"] == "14:00")
    check("appointment notes correct", appt and "Dr. Smith" in (appt["notes"] or ""))

    if appt:
        aid = appt["id"]

        # Detail view
        update, ctx = await run_callback(f"appts:detail:{aid}", ctx)
        check("appt detail responds", update.callback_query.edit_message_text.called)
        text = update.callback_query.edit_message_text.call_args[0][0]
        check("detail shows title", "Dentist Cleaning" in text)

        # Edit title
        update, ctx = await run_callback(f"appts:editfield:{aid}:title", ctx)
        await run_text("Dental Cleaning", ctx)
        with db() as conn:
            a = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        check("appt title edited", a and a["title"] == "Dental Cleaning")

        # Edit date
        update, ctx = await run_callback(f"appts:editfield:{aid}:event_date", ctx)
        await run_text("April 20 2026", ctx)
        with db() as conn:
            a = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        check("appt date edited", a and a["event_date"] == "2026-04-20")

        # Edit time
        update, ctx = await run_callback(f"appts:editfield:{aid}:event_time", ctx)
        await run_text("3:30pm", ctx)
        with db() as conn:
            a = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        check("appt time edited", a and a["event_time"] == "15:30")

        # Edit notes
        update, ctx = await run_callback(f"appts:editfield:{aid}:notes", ctx)
        await run_text("Updated: bring x-ray records too", ctx)
        with db() as conn:
            a = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        check("appt notes edited", a and "x-ray" in (a["notes"] or ""))

        # Mark done
        update, ctx = await run_callback(f"appts:done:{aid}", ctx)
        with db() as conn:
            a = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        check("appt marked done", a and a["done"] == 1)

        # Reopen
        update, ctx = await run_callback(f"appts:undone:{aid}", ctx)
        with db() as conn:
            a = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        check("appt reopened", a and a["done"] == 0)

        # Delete
        update, ctx = await run_callback(f"appts:delete:{aid}", ctx)
        update, ctx = await run_callback(f"appts:confirm_delete:{aid}", ctx)
        with db() as conn:
            a = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        check("appt deleted", a is None)

    # Test add with skip time and skip notes
    logger.info("  Testing skip flows...")
    update, ctx = await run_callback("appts:add", ctx)
    await run_text("Railway Trial Ends", ctx)
    # Pick category
    update, ctx = await run_callback("appts:category:financial", ctx)
    await run_text("March 29", ctx)

    # Skip time via button
    update = make_update(data="appts:skip_time")
    ctx.user_data["awaiting"] = "appt_time"  # Ensure state is correct
    ctx.user_data["appt_title"] = "Railway Trial Ends"
    ctx.user_data["appt_date"] = "2026-03-29"
    ctx.user_data["appt_category"] = "financial"
    await appts_callback(update, ctx)
    check("skip_time sets awaiting notes", ctx.user_data.get("awaiting") == "appt_notes")

    # Skip notes via button → goes to priority picker
    update2 = make_update(data="appts:skip_notes")
    ctx.user_data["appt_title"] = "Railway Trial Ends"
    ctx.user_data["appt_date"] = "2026-03-29"
    ctx.user_data["appt_time"] = None
    ctx.user_data["appt_category"] = "financial"
    await appts_callback(update2, ctx)
    check("skip_notes shows priority picker", ctx.user_data.get("awaiting") is None)

    # Accept default priority → saves
    update3, ctx = await run_callback("appts:priority_ok", ctx)

    with db() as conn:
        a = conn.execute("SELECT * FROM appointments WHERE chat_id = ? AND title = 'Railway Trial Ends'", (CHAT_ID,)).fetchone()
    check("skip-flow appointment saved", a is not None)
    check("no time on skip-flow", a and a["event_time"] is None)


async def test_appointments_in_week_view():
    """Test that appointments appear in week view."""
    logger.info("\n═══ APPOINTMENTS IN WEEK VIEW ═══")

    # Add appointment for this week
    d = today() + timedelta(days=2)
    with db() as conn:
        conn.execute(
            "INSERT INTO appointments (chat_id, title, event_date, event_time) VALUES (?, ?, ?, ?)",
            (CHAT_ID, "Test Appt", d.isoformat(), "10:00"),
        )

    # View this week
    update, ctx = await run_callback("week:view")
    text = update.callback_query.edit_message_text.call_args[0][0]
    check("appointment shows in week view", "Test Appt" in text)

    # Clean up
    with db() as conn:
        conn.execute("DELETE FROM appointments WHERE chat_id = ? AND title = 'Test Appt'", (CHAT_ID,))


async def test_settings():
    """Test Settings: view, schedule, shift type, week days, override."""
    logger.info("\n═══ SETTINGS ═══")
    ctx = make_context()

    # View settings
    update, ctx = await run_callback("settings:view", ctx)
    check("settings:view responds", update.callback_query.edit_message_text.called)

    # View schedule
    update, ctx = await run_callback("settings:schedule", ctx)
    check("settings:schedule responds", update.callback_query.edit_message_text.called)

    # Edit shift type
    update, ctx = await run_callback("settings:edit_shift_type", ctx)
    check("shift type edit sets awaiting", ctx.user_data.get("awaiting") == "settings_shift_type")
    await run_text("7p-7a", ctx)
    with db() as conn:
        shift = conn.execute("SELECT * FROM shifts WHERE chat_id = ?", (CHAT_ID,)).fetchone()
    check("shift type updated", shift and shift["shift_type"] == "7p-7a")

    # Edit week 1 days
    update, ctx = await run_callback("settings:edit_w1", ctx)
    check("week1 edit mode", ctx.user_data.get("settings_editing") == "week1")

    # Select days — this goes through button_router which detects settings_editing
    # and routes to handle_settings_day_select
    await run_callback("onboard:day:0", ctx)  # Mon
    await run_callback("onboard:day:2", ctx)  # Wed
    await run_callback("onboard:day:4", ctx)  # Fri
    await run_callback("onboard:days_done", ctx)

    with db() as conn:
        shift = conn.execute("SELECT * FROM shifts WHERE chat_id = ?", (CHAT_ID,)).fetchone()
    check("week1 days updated via settings", shift and json.loads(shift["week1_days"]) == [0, 2, 4])

    # Override: working today
    update, ctx = await run_callback("settings:override", ctx)
    check("override menu responds", update.callback_query.edit_message_text.called)

    update, ctx = await run_callback("settings:override_on:0", ctx)
    with db() as conn:
        override = conn.execute(
            "SELECT * FROM shift_overrides WHERE chat_id = ? AND override_date = ?",
            (CHAT_ID, today().isoformat())
        ).fetchone()
    check("override saved: working today", override and override["is_working"] == 1)

    # Override: off tomorrow
    update, ctx = await run_callback("settings:override_off:1", ctx)
    tomorrow = today() + timedelta(days=1)
    with db() as conn:
        override = conn.execute(
            "SELECT * FROM shift_overrides WHERE chat_id = ? AND override_date = ?",
            (CHAT_ID, tomorrow.isoformat())
        ).fetchone()
    check("override saved: off tomorrow", override and override["is_working"] == 0)

    # Notification settings
    update, ctx = await run_callback("settings:notify", ctx)
    check("notification settings responds", update.callback_query.edit_message_text.called)

    # Payday settings
    update, ctx = await run_callback("settings:payday", ctx)
    check("payday settings responds", update.callback_query.edit_message_text.called)


async def test_capture_menu():
    """Test Capture/Inbox menu."""
    logger.info("\n═══ CAPTURE / INBOX ═══")
    ctx = make_context()

    update, ctx = await run_callback("capture:start", ctx)
    check("capture menu responds", update.callback_query.edit_message_text.called)

    # Legacy appointment route
    update, ctx = await run_callback("capture:appointment", ctx)
    check("capture:appointment sets awaiting", ctx.user_data.get("awaiting") == "appt_title")


async def test_menu_button():
    """Test menu:main button."""
    logger.info("\n═══ MENU ═══")
    update, ctx = await run_callback("menu:main")
    check("menu:main responds", update.callback_query.edit_message_text.called)


async def test_delete_everything():
    """Delete ALL data and verify clean state."""
    logger.info("\n═══ DELETE EVERYTHING ═══")

    with db() as conn:
        tables = ["appointments", "notes", "medications", "credentials",
                   "car_events", "partner_dates", "partners", "bills",
                   "shift_overrides", "shifts"]
        for t in tables:
            conn.execute(f"DELETE FROM {t} WHERE chat_id = ?", (CHAT_ID,))
        conn.execute("DELETE FROM users WHERE chat_id = ?", (CHAT_ID,))

    # Verify empty
    with db() as conn:
        for t in ["users", "shifts", "bills", "car_events", "credentials",
                   "partners", "medications", "notes", "appointments"]:
            count = conn.execute(f"SELECT COUNT(*) as c FROM {t} WHERE chat_id = ?", (CHAT_ID,)).fetchone()
            check(f"{t} is empty", count and count["c"] == 0)


async def main():
    """Run all tests."""
    init_db()
    # Create test user
    ensure_user(CHAT_ID, TEST_NAME)

    logger.info("═" * 60)
    logger.info("BUTLER BOT COMPREHENSIVE TEST")
    logger.info("═" * 60)

    # RUN 1: Full lifecycle
    logger.info("\n🔄 RUN 1: Full Lifecycle Test\n")

    await test_onboarding()
    await test_today_view()
    await test_week_view()
    await test_bills_crud()
    await test_partners_crud()
    await test_car_crud()
    await test_credentials_crud()
    await test_meds_crud()
    await test_notes_crud()
    await test_appointments_crud()
    await test_appointments_in_week_view()
    await test_settings()
    await test_capture_menu()
    await test_menu_button()

    # Delete everything
    await test_delete_everything()

    # RUN 2: Do it all again to prove clean state works
    logger.info("\n\n🔄 RUN 2: Fresh Start After Delete\n")

    ensure_user(CHAT_ID, TEST_NAME)
    await test_onboarding()
    await test_today_view()
    await test_week_view()
    await test_appointments_crud()
    await test_bills_crud()

    # ═══ SUMMARY ═══
    logger.info("\n" + "═" * 60)
    logger.info("TEST RESULTS SUMMARY")
    logger.info("═" * 60)

    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    total = len(results)

    logger.info(f"\n  ✅ Passed: {passed}/{total}")
    logger.info(f"  ❌ Failed: {failed}/{total}")

    if errors:
        logger.info(f"\n  ERRORS ({len(errors)}):")
        for e in errors:
            logger.info(f"    ❌ {e}")
    else:
        logger.info("\n  🎉 ALL TESTS PASSED — EVERY BUTTON WORKS")

    # Clean up
    if os.path.exists("test_butler.db"):
        os.remove("test_butler.db")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
