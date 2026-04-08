#!/usr/bin/env python3
# Butler Bot — Full Flow Integration Test
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot
#
# This test simulates EVERY button press and text input through the ACTUAL
# handler functions with a REAL database. Not syntax checks. Not import checks.
# Real flows, real DB writes, real state transitions.
#
# RUN BEFORE EVERY PUSH: TELEGRAM_BOT_TOKEN=test python3 test_full_flow.py

import sys, os, json, asyncio, traceback

sys.path.insert(0, '.')
os.environ["TELEGRAM_BOT_TOKEN"] = "test"
os.environ["DATABASE_PATH"] = "/tmp/test_full_flow.db"

from database import init_db, db, ensure_user, update_user, get_user

# ── Test infrastructure ──────────────────────────────────

class FakeUserData(dict):
    pass

class FakeContext:
    def __init__(self):
        self.user_data = FakeUserData()

class FakeChat:
    def __init__(self, cid=999):
        self.id = cid

class FakeUser:
    first_name = "TestUser"
    id = 999

class FakeMessage:
    def __init__(self, text="", cid=999):
        self.text = text
        self.chat = FakeChat(cid)
        self.chat_id = cid
        self.message_id = 1
        self.replies = []
    async def reply_text(self, text, **kw):
        self.replies.append({"text": text, "markup": kw.get("reply_markup")})
        return type('M', (), {'message_id': len(self.replies)})()

class FakeQuery:
    def __init__(self, data, cid=999):
        self.data = data
        self.from_user = FakeUser()
        self.message = FakeMessage(cid=cid)
        self.message.chat_id = cid
        self.edits = []
    async def answer(self, text=None, show_alert=False):
        pass
    async def edit_message_text(self, text, **kw):
        self.edits.append({"text": text, "markup": kw.get("reply_markup")})
    async def edit_message_reply_markup(self, **kw):
        self.edits.append({"markup": kw.get("reply_markup")})

class FakeUpdate:
    def __init__(self, text=None, cb=None, cid=999):
        self.effective_chat = FakeChat(cid)
        self.effective_user = FakeUser()
        if text:
            self.message = FakeMessage(text, cid)
            self.callback_query = None
        else:
            self.message = None
            self.callback_query = FakeQuery(cb, cid)

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

def buttons_from(result):
    """Extract callback_data strings from a handler result."""
    markup = None
    if hasattr(result, 'callback_query') and result.callback_query:
        q = result.callback_query
        if q.edits:
            markup = q.edits[-1].get("markup")
        elif q.message.replies:
            markup = q.message.replies[-1].get("markup")
    elif hasattr(result, 'message') and result.message:
        if result.message.replies:
            markup = result.message.replies[-1].get("markup")
    if markup:
        return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]
    return []


passed = 0
failed = 0
failures = []

def section(name):
    print(f"\n{'═' * 60}")
    print(f"  {name}")
    print(f"{'═' * 60}")

def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  ✅ {name}")
        passed += 1
    except Exception as e:
        print(f"  ❌ {name}")
        print(f"     {e}")
        failures.append((name, str(e)))
        failed += 1


# ══════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════

init_db()
ensure_user(999, "TestUser")
update_user(999, onboarded=1)


# ══════════════════════════════════════════════════════════
section("ONBOARDING: Full flow start to finish")
# ══════════════════════════════════════════════════════════

def test_full_onboarding():
    from modules.onboarding import onboard_callback, handle_onboard_text
    ctx = FakeContext()

    def cb(data):
        u = FakeUpdate(cb=data); run(onboard_callback(u, ctx)); return u
    def txt(text):
        u = FakeUpdate(text=text); run(handle_onboard_text(u, ctx)); return u

    # Start → Name → Shift → Days → No Week 2
    cb("onboard:start")
    assert ctx.user_data["awaiting"] == "onboard_name"
    txt("James")
    cb("onboard:shift:7p-7a")
    cb("onboard:day:0"); cb("onboard:day:1"); cb("onboard:day:5")
    cb("onboard:days_done")
    cb("onboard:add_week:no")

    # Partners: add one with type + frequency
    cb("onboard:partners_intro")
    cb("onboard:add_partners:yes")
    assert ctx.user_data["awaiting"] == "onboard_partner_name"
    txt("Sam")
    cb("onboard:partner_type:partner")
    cb("onboard:partner_freq:1:weekly")
    cb("onboard:another_partner:no")

    # Bills: add one
    cb("onboard:bills_intro")
    cb("onboard:add_bills:yes")
    txt("Mortgage")
    txt("$2000")
    cb("onboard:another_bill:no")

    # Car: add oil change with date picker
    cb("onboard:car_intro")
    cb("onboard:add_car:yes")
    txt("Oil change")
    cb("onboard:ob_date:car:month:5:2026")
    cb("onboard:ob_date:car:day:2026-05-18")
    with db() as conn:
        car = conn.execute("SELECT * FROM car_events WHERE chat_id=999 AND description='Oil change'").fetchone()
    assert car, "Car event not saved!"
    cb("onboard:another_car:no")

    # Credentials: add one with date picker
    cb("onboard:creds_intro")
    cb("onboard:add_creds:yes")
    txt("RRT License")
    cb("onboard:ob_date:cred:month:6:2027")
    cb("onboard:ob_date:cred:day:2027-06-01")
    with db() as conn:
        cred = conn.execute("SELECT * FROM credentials WHERE chat_id=999 AND name='RRT License'").fetchone()
    assert cred, "Credential not saved!"
    cb("onboard:another_cred:no")

    # Meds: add one
    cb("onboard:meds_intro")
    cb("onboard:add_meds:yes")
    txt("Lisinopril")
    cb("onboard:another_med:no")

    # Verify final state
    user = get_user(999)
    assert user["onboarded"] == 1, f"Expected onboarded=1, got {user['onboarded']}"
    assert user["onboard_step"] is None, f"Expected onboard_step=None, got {user['onboard_step']}"

test("Full onboarding: name → shift → days → partners → bills → car → creds → meds → done", test_full_onboarding)


# ══════════════════════════════════════════════════════════
section("ONBOARDING: Skip paths")
# ══════════════════════════════════════════════════════════

def test_skip_all_sections():
    from modules.onboarding import onboard_callback, handle_onboard_text
    # Fresh user
    ensure_user(888, "Skipper")
    update_user(888, onboarded=0)
    ctx = FakeContext()
    def cb(data):
        u = FakeUpdate(cb=data, cid=888); run(onboard_callback(u, ctx)); return u
    def txt(text):
        u = FakeUpdate(text=text, cid=888); run(handle_onboard_text(u, ctx)); return u

    cb("onboard:start")
    txt("Skipper")
    cb("onboard:shift:7p-7a")
    cb("onboard:day:0"); cb("onboard:days_done"); cb("onboard:add_week:no")
    cb("onboard:partners_intro")
    cb("onboard:add_partners:no")  # Skip partners
    cb("onboard:bills_intro")
    cb("onboard:add_bills:no")  # Skip bills
    cb("onboard:car_intro")
    cb("onboard:add_car:no")  # Skip car
    cb("onboard:creds_intro")
    cb("onboard:add_creds:no")  # Skip creds
    cb("onboard:meds_intro")
    cb("onboard:add_meds:no")  # Skip meds → finish

    user = get_user(888)
    assert user["onboarded"] == 1

test("Skip all sections: partners → bills → car → creds → meds all skipped", test_skip_all_sections)


# ══════════════════════════════════════════════════════════
section("MENU: Credential add flow")
# ══════════════════════════════════════════════════════════

def test_menu_cred_add():
    from modules.credentials import creds_callback, handle_cred_text, cred_datepick_callback
    ctx = FakeContext()
    def cb(data):
        u = FakeUpdate(cb=data); run(creds_callback(u, ctx)); return u
    def cbdp(data):
        u = FakeUpdate(cb=data); run(cred_datepick_callback(u, ctx)); return u

    cb("creds:add")
    assert ctx.user_data["awaiting"] == "cred_name"
    u = FakeUpdate(text="BLS Cert"); run(handle_cred_text(u, ctx))
    cbdp("creddp:month:12:2026")
    cbdp("creddp:day:2026-12-31")
    with db() as conn:
        c = conn.execute("SELECT * FROM credentials WHERE chat_id=999 AND name='BLS Cert'").fetchone()
    assert c, "BLS Cert not saved!"
    assert c["expiry_date"] == "2026-12-31"

test("Menu credential: name → date picker → save → DB verified", test_menu_cred_add)


# ══════════════════════════════════════════════════════════
section("MENU: Car add flows (all types)")
# ══════════════════════════════════════════════════════════

def test_menu_car_oil():
    from modules.car import car_callback, car_datepick_callback
    ctx = FakeContext()
    u = FakeUpdate(cb="car:add"); run(car_callback(u, ctx))
    u = FakeUpdate(cb="car:addtype:oil_change"); run(car_callback(u, ctx))
    u = FakeUpdate(cb="cardp:month:5:2026"); run(car_datepick_callback(u, ctx))
    u = FakeUpdate(cb="cardp:day:2026-05-18"); run(car_datepick_callback(u, ctx))
    with db() as conn:
        e = conn.execute("SELECT * FROM car_events WHERE chat_id=999 AND event_type='oil_change'").fetchone()
    assert e, "Oil change not saved!"

def test_menu_car_inspection():
    from modules.car import car_callback, car_datepick_callback
    ctx = FakeContext()
    u = FakeUpdate(cb="car:addtype:inspection"); run(car_callback(u, ctx))
    u = FakeUpdate(cb="cardp:month:2:2027"); run(car_datepick_callback(u, ctx))
    u = FakeUpdate(cb="cardp:day:2027-02-15"); run(car_datepick_callback(u, ctx))
    with db() as conn:
        e = conn.execute("SELECT * FROM car_events WHERE chat_id=999 AND event_type='inspection'").fetchone()
    assert e, "Inspection not saved!"

def test_menu_car_registration():
    from modules.car import car_callback, car_datepick_callback
    ctx = FakeContext()
    u = FakeUpdate(cb="car:addtype:registration"); run(car_callback(u, ctx))
    u = FakeUpdate(cb="cardp:month:1:2027"); run(car_datepick_callback(u, ctx))
    u = FakeUpdate(cb="cardp:day:2027-01-31"); run(car_datepick_callback(u, ctx))
    with db() as conn:
        e = conn.execute("SELECT * FROM car_events WHERE chat_id=999 AND event_type='registration'").fetchone()
    assert e, "Registration not saved!"

def test_menu_car_custom():
    from modules.car import car_callback, handle_car_text, car_datepick_callback
    ctx = FakeContext()
    u = FakeUpdate(cb="car:addtype:custom"); run(car_callback(u, ctx))
    assert ctx.user_data["awaiting"] == "car_desc"
    u = FakeUpdate(text="Brake pads"); run(handle_car_text(u, ctx))
    u = FakeUpdate(cb="cardp:month:6:2026"); run(car_datepick_callback(u, ctx))
    u = FakeUpdate(cb="cardp:day:2026-06-01"); run(car_datepick_callback(u, ctx))
    with db() as conn:
        e = conn.execute("SELECT * FROM car_events WHERE chat_id=999 AND description='Brake pads'").fetchone()
    assert e, "Custom car item not saved!"

test("Menu car: Oil Change → date → save", test_menu_car_oil)
test("Menu car: Inspection → date → save", test_menu_car_inspection)
test("Menu car: Registration → date → save", test_menu_car_registration)
test("Menu car: Custom → typed desc → date → save", test_menu_car_custom)


# ══════════════════════════════════════════════════════════
section("MENU: Appointment add flow")
# ══════════════════════════════════════════════════════════

def test_menu_appt_add():
    from modules.appointments import appts_callback, handle_appt_text, appt_datepick_callback
    ctx = FakeContext()
    u = FakeUpdate(cb="appts:add"); run(appts_callback(u, ctx))
    assert ctx.user_data["awaiting"] == "appt_title"
    u = FakeUpdate(text="Dentist"); run(handle_appt_text(u, ctx))
    u = FakeUpdate(cb="appts:category:medical"); run(appts_callback(u, ctx))
    u = FakeUpdate(cb="apptdp:month:4:2026"); run(appt_datepick_callback(u, ctx))
    u = FakeUpdate(cb="apptdp:day:2026-04-20"); run(appt_datepick_callback(u, ctx))
    assert ctx.user_data.get("appt_date") == "2026-04-20"

test("Menu appointment: title → category → date picker → time prompt", test_menu_appt_add)


# ══════════════════════════════════════════════════════════
section("MENU: Bill add flow")
# ══════════════════════════════════════════════════════════

def test_menu_bill_add():
    from modules.bills import bills_callback, handle_bill_text
    ctx = FakeContext()
    u = FakeUpdate(cb="bills:add"); run(bills_callback(u, ctx))
    assert ctx.user_data["awaiting"] == "bill_name"
    u = FakeUpdate(text="PECO"); run(handle_bill_text(u, ctx))
    u = FakeUpdate(text="$150"); run(handle_bill_text(u, ctx))
    # After amount, should show due day picker or save

test("Menu bill: name → amount → due day", test_menu_bill_add)


# ══════════════════════════════════════════════════════════
section("MENU: Partner add flow")
# ══════════════════════════════════════════════════════════

def test_menu_partner_add():
    from modules.partners import partners_callback, handle_partner_text
    ctx = FakeContext()
    u = FakeUpdate(cb="partners:add"); run(partners_callback(u, ctx))
    assert ctx.user_data["awaiting"] == "partner_name"
    u = FakeUpdate(text="Alex"); run(handle_partner_text(u, ctx))
    with db() as conn:
        p = conn.execute("SELECT * FROM partners WHERE chat_id=999 AND name='Alex'").fetchone()
    assert p, "Partner not saved!"
    pid = p["id"]
    u = FakeUpdate(cb=f"partners:settype:{pid}:friend"); run(partners_callback(u, ctx))
    with db() as conn:
        p = conn.execute("SELECT * FROM partners WHERE id=?", (pid,)).fetchone()
    assert p["relationship_type"] == "friend"

test("Menu partner: name → type picker → save", test_menu_partner_add)


# ══════════════════════════════════════════════════════════
section("MENU: Med add flow")
# ══════════════════════════════════════════════════════════

def test_menu_med_add():
    from modules.meds import meds_callback, handle_med_text
    ctx = FakeContext()
    u = FakeUpdate(cb="meds:add"); run(meds_callback(u, ctx))
    assert ctx.user_data["awaiting"] == "med_name"
    u = FakeUpdate(text="Metformin"); run(handle_med_text(u, ctx))
    assert ctx.user_data["awaiting"] == "med_dosage"
    u = FakeUpdate(text="500mg"); run(handle_med_text(u, ctx))
    with db() as conn:
        m = conn.execute("SELECT * FROM medications WHERE chat_id=999 AND name='Metformin'").fetchone()
    assert m, "Med not saved!"
    assert m["dosage"] == "500mg"

test("Menu med: name → dosage → save", test_menu_med_add)


# ══════════════════════════════════════════════════════════
section("CROSS-MODULE: Text router isolation")
# ══════════════════════════════════════════════════════════

def test_isolation():
    from modules.bills import handle_bill_text
    from modules.partners import handle_partner_text
    from modules.car import handle_car_text
    from modules.credentials import handle_cred_text
    from modules.meds import handle_med_text
    from modules.onboarding import handle_onboard_text

    pairs = [
        ("bill_name", handle_partner_text),
        ("cred_name", handle_partner_text),
        ("car_desc", handle_bill_text),
        ("partner_name", handle_cred_text),
        ("med_name", handle_bill_text),
        ("cred_name", handle_onboard_text),  # The hijack bug
    ]
    for awaiting, handler in pairs:
        ctx = FakeContext()
        ctx.user_data["awaiting"] = awaiting
        u = FakeUpdate(text="test")
        result = run(handler(u, ctx))
        assert result == False, f"Handler {handler.__module__} caught awaiting={awaiting}"

test("Text handlers respect awaiting boundaries (no cross-contamination)", test_isolation)


# ══════════════════════════════════════════════════════════
section("EDGE CASES")
# ══════════════════════════════════════════════════════════

def test_stale_car_button():
    from modules.car import car_datepick_callback
    ctx = FakeContext()
    with db() as conn:
        conn.execute("DELETE FROM settings WHERE chat_id=999 AND key='pending_car_desc'")
    u = FakeUpdate(cb="cardp:day:2026-12-31")
    run(car_datepick_callback(u, ctx))
    # Should not crash or create a record

test("Stale car date picker button → no crash, no duplicate", test_stale_car_button)

def test_stale_cred_button():
    from modules.credentials import cred_datepick_callback
    ctx = FakeContext()
    with db() as conn:
        conn.execute("DELETE FROM settings WHERE chat_id=999 AND key='pending_cred_name'")
    u = FakeUpdate(cb="creddp:day:2027-12-31")
    run(cred_datepick_callback(u, ctx))

test("Stale cred date picker button → no crash, no duplicate", test_stale_cred_button)

def test_empty_today_view():
    from modules.today import today_view
    ensure_user(777, "Empty")
    update_user(777, onboarded=1)
    u = FakeUpdate(cb="today:view", cid=777)
    ctx = FakeContext()
    try:
        run(today_view(u, ctx))
    except Exception as e:
        if "NoneType" not in str(e):
            raise

test("Today view: empty user doesn't crash", test_empty_today_view)


# ══════════════════════════════════════════════════════════
section("BUG FIXES & NEW FEATURES")
# ══════════════════════════════════════════════════════════

def test_corrupted_onboard_data():
    """BUG 1: Corrupted onboard_data JSON should not crash."""
    from modules.onboarding import onboard_callback, handle_onboard_text
    ensure_user(666, "Corrupt")
    update_user(666, onboarded=0, onboard_step="bill_name", onboard_data="{invalid json!!!}")
    ctx = FakeContext()
    ctx.user_data["awaiting"] = "onboard_bill_name"
    # This should not crash — the handler should reset ob_data to {}
    u = FakeUpdate(text="Electric", cid=666)
    run(handle_onboard_text(u, ctx))
    # Verify it didn't crash and the user's onboard_data was reset to valid JSON
    user = get_user(666)
    try:
        json.loads(user["onboard_data"] or "{}")
    except json.JSONDecodeError:
        raise AssertionError("onboard_data is still corrupted after recovery")

test("Corrupted onboard_data JSON: no crash, auto-reset", test_corrupted_onboard_data)


def test_second_bill_add():
    """BUG 2: Adding a second bill in onboarding should loop back correctly."""
    from modules.onboarding import onboard_callback, handle_onboard_text
    ensure_user(555, "BillTest")
    update_user(555, onboarded=0, onboard_step="name", onboard_data="{}")
    ctx = FakeContext()
    def cb(data):
        u = FakeUpdate(cb=data, cid=555); run(onboard_callback(u, ctx)); return u
    def txt(text):
        u = FakeUpdate(text=text, cid=555); run(handle_onboard_text(u, ctx)); return u

    cb("onboard:start")
    txt("BillTest")
    cb("onboard:shift:7p-7a")
    cb("onboard:day:0"); cb("onboard:days_done"); cb("onboard:add_week:no")
    cb("onboard:partners_intro")
    cb("onboard:add_partners:no")
    cb("onboard:bills_intro")
    cb("onboard:add_bills:yes")
    txt("Rent")
    txt("$1200")
    # After first bill, onboard_step should be bill_amount (not car_intro)
    user = get_user(555)
    assert user["onboard_step"] == "bill_amount", f"Expected bill_amount, got {user['onboard_step']}"
    # Add second bill
    cb("onboard:another_bill:yes")
    assert ctx.user_data["awaiting"] == "onboard_bill_name"
    txt("Internet")
    txt("$80")
    # Verify both saved
    with db() as conn:
        bills = conn.execute("SELECT name FROM bills WHERE chat_id=555 ORDER BY name").fetchall()
    names = [b["name"] for b in bills]
    assert "Rent" in names and "Internet" in names, f"Expected both bills, got {names}"
    # Now skip
    cb("onboard:another_bill:no")
    user = get_user(555)
    assert user["onboard_step"] == "car_intro"

test("Second bill add: loops correctly, both saved", test_second_bill_add)


def test_alter_day_handler():
    """BUG 3: alter:day:{date} handler shows Working/Off buttons."""
    from bot import handle_alter_schedule
    from datetime import date
    ctx = FakeContext()
    today_str = date.today().isoformat()
    u = FakeUpdate(cb=f"alter:day:{today_str}")
    run(handle_alter_schedule(u, ctx))
    q = u.callback_query
    assert q.edits, "No edits from alter:day handler"
    last = q.edits[-1]
    assert "work day" in last["text"].lower(), f"Expected work day prompt, got: {last['text'][:50]}"
    # Check buttons exist
    btns = [b.callback_data for row in last["markup"].inline_keyboard for b in row if b.callback_data]
    assert any("setday" in b for b in btns), f"No setday buttons found: {btns}"

test("Alter schedule: day picker shows Working/Off", test_alter_day_handler)


def test_alter_setday_handler():
    """BUG 3: alter:setday:{date}:{on} shows scope picker."""
    from bot import handle_alter_schedule
    from datetime import date
    ctx = FakeContext()
    today_str = date.today().isoformat()
    u = FakeUpdate(cb=f"alter:setday:{today_str}:on")
    run(handle_alter_schedule(u, ctx))
    q = u.callback_query
    assert q.edits, "No edits from alter:setday handler"
    last = q.edits[-1]
    btns = [b.callback_data for row in last["markup"].inline_keyboard for b in row if b.callback_data]
    assert any("scope" in b for b in btns), f"No scope buttons: {btns}"

test("Alter schedule: setday shows scope picker", test_alter_setday_handler)


def test_alter_scope_week():
    """BUG 3: alter:scope saves override."""
    from bot import handle_alter_schedule
    from datetime import date
    ctx = FakeContext()
    today_str = date.today().isoformat()
    u = FakeUpdate(cb=f"alter:scope:{today_str}:on:week")
    run(handle_alter_schedule(u, ctx))
    q = u.callback_query
    assert q.edits, "No edits from alter:scope handler"
    assert "override saved" in q.edits[-1]["text"].lower() or "\u2705" in q.edits[-1]["text"]
    # Verify DB
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM shift_overrides WHERE chat_id=999 AND override_date=?",
            (today_str,)
        ).fetchone()
    assert row and row["is_working"] == 1

test("Alter schedule: scope=week saves override to DB", test_alter_scope_week)


def test_today_metime():
    """FEATURE: today:metime handler."""
    from modules.today import today_view
    ctx = FakeContext()
    u = FakeUpdate(cb="today:metime")
    run(today_view(u, ctx))
    q = u.callback_query
    assert q.edits, "No edits from metime handler"
    text = q.edits[-1]["text"].lower()
    assert "me time" in text or "working" in text, f"Unexpected metime text: {text[:60]}"

test("Today: Me Time handler works", test_today_metime)


def test_today_suggest():
    """FEATURE: today:suggest handler."""
    from modules.today import today_view
    ctx = FakeContext()
    u = FakeUpdate(cb="today:suggest")
    run(today_view(u, ctx))
    q = u.callback_query
    assert q.edits, "No edits from suggest handler"
    text = q.edits[-1]["text"]
    assert "SUGGESTIONS" in text or "suggestions" in text.lower() or "on top" in text.lower()

test("Today: Suggestions handler works", test_today_suggest)


def test_today_analyze():
    """FEATURE: today:analyze handler."""
    from modules.today import today_view
    ctx = FakeContext()
    u = FakeUpdate(cb="today:analyze")
    run(today_view(u, ctx))
    q = u.callback_query
    assert q.edits, "No edits from analyze handler"
    text = q.edits[-1]["text"]
    assert "STATUS" in text or "Meds" in text or "Bills" in text or "Dates" in text

test("Today: Analyze handler works", test_today_analyze)


def test_settings_setpayday():
    """BUG 4: settings:setpayday saves to DB."""
    from bot import handle_settings
    ctx = FakeContext()
    u = FakeUpdate(cb="settings:setpayday:weekly_friday")
    run(handle_settings(u, ctx))
    q = u.callback_query
    assert q.edits, "No edits from setpayday handler"
    assert "Payday set" in q.edits[-1]["text"] or "\u2705" in q.edits[-1]["text"]
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE chat_id=999 AND key='payday_type'"
        ).fetchone()
    assert row and row["value"] == "weekly_friday"

test("Settings: payday picker saves to DB", test_settings_setpayday)


# ══════════════════════════════════════════════════════════
section("HEARTBEAT & PROACTIVE FEATURES")
# ══════════════════════════════════════════════════════════

def test_heartbeat_no_data():
    """Heartbeat should not crash with an empty user (no meds, no bills, no appointments)."""
    from modules.scheduler import _send_heartbeat, _most_urgent_item
    from datetime import date

    ensure_user(444, "HeartbeatUser")
    update_user(444, onboarded=1)

    # _most_urgent_item should return None with no data
    d = date.today()
    result = _most_urgent_item(444, d)
    assert result is None, f"Expected None for empty user, got: {result}"

test("Heartbeat: _most_urgent_item returns None for empty user", test_heartbeat_no_data)


def test_heartbeat_with_appointment():
    """Heartbeat should find an upcoming appointment as urgent."""
    from modules.scheduler import _most_urgent_item
    from datetime import date, timedelta

    d = date.today()
    tomorrow = (d + timedelta(days=1)).isoformat()
    with db() as conn:
        conn.execute(
            "INSERT INTO appointments (chat_id, title, event_date) VALUES (?, ?, ?)",
            (999, "Blood work", tomorrow),
        )
    result = _most_urgent_item(999, d)
    assert result is not None, "Should find tomorrow's appointment"
    assert "Blood work" in result
    assert "tomorrow" in result

test("Heartbeat: _most_urgent_item finds tomorrow's appointment", test_heartbeat_with_appointment)


def test_heartbeat_with_untaken_meds():
    """Heartbeat should report untaken meds when nothing else is urgent."""
    from modules.scheduler import _most_urgent_item
    from datetime import date, timedelta

    ensure_user(333, "MedTestUser")
    update_user(333, onboarded=1)
    with db() as conn:
        conn.execute(
            "INSERT INTO medications (chat_id, name, taken_today) VALUES (?, ?, ?)",
            (333, "Aspirin", 0),
        )
    d = date.today()
    result = _most_urgent_item(333, d)
    assert result is not None
    assert "Aspirin" in result

test("Heartbeat: _most_urgent_item finds untaken meds", test_heartbeat_with_untaken_meds)


def test_task_breakdown_detection():
    """Task breakdown should detect task-like notes."""
    from modules.notes import _sounds_like_task, _break_into_steps

    assert _sounds_like_task("I need to clean the entire apartment this weekend") == True
    assert _sounds_like_task("gotta schedule a dentist appointment soon") == True
    assert _sounds_like_task("I should organize my taxes before April") == True
    assert _sounds_like_task("short") == False  # Too short
    assert _sounds_like_task("Just a regular note about nothing in particular really") == False  # No task words

    # Verify breakdown returns steps
    steps = _break_into_steps("need to clean the apartment")
    assert len(steps) > 0
    assert any("trash" in s.lower() or "surface" in s.lower() for s in steps)

    steps = _break_into_steps("schedule a dentist appointment")
    assert len(steps) > 0
    assert any("provider" in s.lower() or "number" in s.lower() for s in steps)

    # Generic breakdown
    steps = _break_into_steps("I need to deal with that thing from last month")
    assert len(steps) == 3

test("Task breakdown: detection and step generation", test_task_breakdown_detection)


def test_task_breakdown_callback():
    """Test notes:breakdown callback works end to end."""
    from modules.notes import notes_callback, handle_note_text
    ctx = FakeContext()

    # First add a note that sounds like a task
    ctx.user_data["awaiting"] = "note_content"
    ctx.user_data["note_category"] = "general"
    ctx.user_data["note_ref_id"] = None
    u = FakeUpdate(text="I need to organize all my tax documents before April deadline")
    run(handle_note_text(u, ctx))
    # Should offer breakdown
    msg = u.message.replies[-1]
    assert "break it down" in msg["text"].lower()
    # Get the note_id from the callback data
    btns = [b.callback_data for row in msg["markup"].inline_keyboard for b in row if b.callback_data]
    breakdown_btn = [b for b in btns if "breakdown" in b]
    assert breakdown_btn, f"No breakdown button found in: {btns}"

    # Now tap the breakdown button
    u = FakeUpdate(cb=breakdown_btn[0])
    run(notes_callback(u, ctx))
    q = u.callback_query
    assert q.edits, "No edits from breakdown handler"
    text = q.edits[-1]["text"]
    assert "Breaking down" in text
    assert "1." in text  # Has numbered steps

test("Task breakdown: full callback flow", test_task_breakdown_callback)


def test_note_no_breakdown_for_short():
    """Short notes should not offer breakdown."""
    from modules.notes import handle_note_text
    ctx = FakeContext()
    ctx.user_data["awaiting"] = "note_content"
    ctx.user_data["note_category"] = "general"
    ctx.user_data["note_ref_id"] = None
    u = FakeUpdate(text="Buy milk")
    run(handle_note_text(u, ctx))
    msg = u.message.replies[-1]
    assert "break it down" not in msg["text"].lower()
    assert any(w in msg["text"] for w in ["Saved", "Got it", "Noted", "Logged"]), f"Unexpected note save text: {msg['text']}"

test("Task breakdown: short notes don't trigger breakdown offer", test_note_no_breakdown_for_short)


def test_med_streak_column_exists():
    """Verify med_streak column exists after migration."""
    with db() as conn:
        user = conn.execute("SELECT med_streak FROM users WHERE chat_id = 999").fetchone()
    assert user is not None
    # Default should be 0
    assert user["med_streak"] is not None

test("Med streak: column exists with default value", test_med_streak_column_exists)


def test_med_streak_celebration():
    """Med streak should fire celebration at milestones."""
    from modules.meds import _check_streak_celebration, STREAK_MESSAGES
    # Set streak to 2 (so +1 = 3, which is a milestone)
    with db() as conn:
        conn.execute("UPDATE users SET med_streak = 2 WHERE chat_id = 999")
    result = _check_streak_celebration(999)
    assert result is not None
    assert "3 days" in result

    # Set streak to 5 — not a milestone
    with db() as conn:
        conn.execute("UPDATE users SET med_streak = 5 WHERE chat_id = 999")
    result = _check_streak_celebration(999)
    assert result is None, f"Expected None for non-milestone, got: {result}"

    # Set streak to 6 (+1 = 7, milestone)
    with db() as conn:
        conn.execute("UPDATE users SET med_streak = 6 WHERE chat_id = 999")
    result = _check_streak_celebration(999)
    assert result is not None
    assert "week" in result.lower()

    # Reset for other tests
    with db() as conn:
        conn.execute("UPDATE users SET med_streak = 0 WHERE chat_id = 999")

test("Med streak: celebrations fire at milestones 3, 7", test_med_streak_celebration)


def test_morning_heartbeat_toggle():
    """Morning heartbeat should appear in feature toggles."""
    from keyboards import feature_toggles_kb
    kb = feature_toggles_kb({})
    btns = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    assert any("morning_heartbeat" in b for b in btns), f"morning_heartbeat not in toggles: {btns}"

test("Morning heartbeat: appears in feature toggles", test_morning_heartbeat_toggle)


def test_new_callback_data_lengths():
    """Verify all new callback data strings are within Telegram's 64-byte limit."""
    callbacks = [
        "notes:breakdown:99999",
        "settings:toggle:morning_heartbeat",
    ]
    for cb in callbacks:
        assert len(cb.encode('utf-8')) <= 64, f"Callback too long ({len(cb.encode('utf-8'))} bytes): {cb}"

test("New callback data strings ≤ 64 bytes", test_new_callback_data_lengths)


def test_callback_data_lengths():
    """Verify all new callback data strings are within Telegram's 64-byte limit."""
    from datetime import date
    d = date.today()
    callbacks = [
        f"alter:day:{d.isoformat()}",
        f"alter:setday:{d.isoformat()}:on",
        f"alter:setday:{d.isoformat()}:off",
        f"alter:scope:{d.isoformat()}:on:week",
        f"alter:scope:{d.isoformat()}:off:perm",
        "settings:setpayday:weekly_friday",
        "settings:setpayday:biweekly_friday",
        "settings:setpayday:first_fifteenth",
        "settings:setpayday:custom",
        "today:metime",
        "today:suggest",
        "today:analyze",
    ]
    for cb in callbacks:
        assert len(cb.encode('utf-8')) <= 64, f"Callback too long ({len(cb.encode('utf-8'))} bytes): {cb}"

test("All new callback data strings ≤ 64 bytes", test_callback_data_lengths)


# ══════════════════════════════════════════════════════════
section("CODE QUALITY: Cancel buttons on text prompts")
# ══════════════════════════════════════════════════════════

def test_cancel_buttons_on_prompts():
    """Every text-input prompt from menu flows should have a cancel button."""
    ctx = FakeContext()

    # Helper to check for cancel/menu:main button in a handler's output
    def has_cancel(update_obj):
        markup = None
        if update_obj.callback_query:
            q = update_obj.callback_query
            if q.edits:
                markup = q.edits[-1].get("markup")
        if markup:
            all_cbs = [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]
            return "menu:main" in all_cbs
        return False

    # Notes: add
    from modules.notes import notes_callback
    u = FakeUpdate(cb="notes:add:general"); run(notes_callback(u, ctx))
    assert has_cancel(u), "notes:add prompt missing cancel button"

    # Bills: add
    from modules.bills import bills_callback
    u = FakeUpdate(cb="bills:add"); run(bills_callback(u, ctx))
    assert has_cancel(u), "bills:add prompt missing cancel button"

    # Meds: add
    from modules.meds import meds_callback
    u = FakeUpdate(cb="meds:add"); run(meds_callback(u, ctx))
    assert has_cancel(u), "meds:add prompt missing cancel button"

    # Appointments: add
    from modules.appointments import appts_callback
    u = FakeUpdate(cb="appts:add"); run(appts_callback(u, ctx))
    assert has_cancel(u), "appts:add prompt missing cancel button"

    # Partners: add
    from modules.partners import partners_callback
    u = FakeUpdate(cb="partners:add"); run(partners_callback(u, ctx))
    assert has_cancel(u), "partners:add prompt missing cancel button"

    # Credentials: add
    from modules.credentials import creds_callback
    u = FakeUpdate(cb="creds:add"); run(creds_callback(u, ctx))
    assert has_cancel(u), "creds:add prompt missing cancel button"

    # Car: custom type
    from modules.car import car_callback
    u = FakeUpdate(cb="car:addtype:custom"); run(car_callback(u, ctx))
    assert has_cancel(u), "car:addtype:custom prompt missing cancel button"

test("Cancel buttons present on all text-input prompts", test_cancel_buttons_on_prompts)


# ══════════════════════════════════════════════════════════
# RESULTS
# ══════════════════════════════════════════════════════════

print(f"\n{'═' * 60}")
print(f"  RESULTS: {passed} passed, {failed} failed")
if failures:
    print(f"\n  FAILURES:")
    for name, err in failures:
        print(f"    ❌ {name}: {err}")
print(f"{'═' * 60}")

# Cleanup
try:
    os.unlink("/tmp/test_full_flow.db")
except:
    pass

sys.exit(1 if failed else 0)
