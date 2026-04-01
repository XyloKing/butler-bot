"""
test_onboarding_flow.py
=======================
Unit tests for the Butler Bot onboarding module (modules/onboarding.py).

Tests use mock objects for Telegram Update/CallbackQuery/Message and call
the actual handler functions directly (no network or DB required; the DB
is an in-memory SQLite injected via monkeypatching).

Run with:  python3 -m pytest test_onboarding_flow.py -v
  or:      python3 test_onboarding_flow.py
"""

import asyncio
import json
import sys
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call

# ── Make sure we can import from the butler-bot directory ──────────────────
sys.path.insert(0, os.path.dirname(__file__))


# ── Minimal stubs for external deps that aren't installed in test env ────────

class _FakeInlineKeyboardButton:
    def __init__(self, text, callback_data=None, **kw):
        self.text = text
        self.callback_data = callback_data


class _FakeInlineKeyboardMarkup:
    def __init__(self, rows):
        self.inline_keyboard = rows


class _FakeUpdate:
    pass


class _FakeCallbackQuery:
    pass


class _FakeTelegramModule(MagicMock):
    """Drop-in stub for the 'telegram' package."""
    InlineKeyboardButton = _FakeInlineKeyboardButton
    InlineKeyboardMarkup = _FakeInlineKeyboardMarkup
    Update = _FakeUpdate
    CallbackQuery = _FakeCallbackQuery


class _FakeExtModule(MagicMock):
    """Drop-in stub for 'telegram.ext'."""
    class ContextTypes:
        DEFAULT_TYPE = None

    class ConversationHandler:
        pass


# Patch telegram imports before importing any bot modules
_fake_tg = _FakeTelegramModule()
sys.modules["telegram"] = _fake_tg
sys.modules["telegram.ext"] = _FakeExtModule()

# In-memory store for fake DB
_USERS_STORE = {}
_SHIFTS_STORE = {}
_PARTNERS_STORE = []


def _fake_ensure_user(chat_id, name):
    if chat_id not in _USERS_STORE:
        _USERS_STORE[chat_id] = {
            "chat_id": chat_id,
            "display_name": name,
            "onboarded": 0,
            "onboard_step": None,
            "onboard_data": "{}",
        }
        return False
    return bool(_USERS_STORE[chat_id]["onboarded"])


def _fake_get_user(chat_id):
    return _USERS_STORE.get(chat_id)


def _fake_update_user(chat_id, **kwargs):
    if chat_id not in _USERS_STORE:
        _USERS_STORE[chat_id] = {
            "chat_id": chat_id, "display_name": None,
            "onboarded": 0, "onboard_step": None, "onboard_data": "{}",
        }
    _USERS_STORE[chat_id].update(kwargs)


class _FakeConn:
    """Fake DB connection context manager."""
    def __init__(self):
        self._last_insert_id = len(_PARTNERS_STORE) + 1

    def execute(self, sql, params=()):
        sql_lower = sql.strip().lower()
        if "insert into partners" in sql_lower:
            name = params[1]
            _PARTNERS_STORE.append({"id": self._last_insert_id, "name": name,
                                    "chat_id": params[0], "relationship_type": None})
            self.lastrowid = self._last_insert_id
            self._last_insert_id += 1
        elif "insert or replace into shifts" in sql_lower:
            _SHIFTS_STORE[params[0]] = {
                "shift_type": params[1],
                "week1_days": json.loads(params[2]),
                "week2_days": json.loads(params[3]),
            }
        elif "update partners" in sql_lower:
            # UPDATE partners SET relationship_type = ? WHERE id = ? AND chat_id = ?
            for p in _PARTNERS_STORE:
                if p["id"] == params[1] and p["chat_id"] == params[2]:
                    p["relationship_type"] = params[0]
        elif "select 1 from partners" in sql_lower:
            # duplicate check
            name = params[1]
            for p in _PARTNERS_STORE:
                if p["chat_id"] == params[0] and p["name"].lower() == name.lower():
                    return self  # non-None = duplicate found
            return _FakeEmptyResult()
        return self

    def fetchone(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class _FakeEmptyResult:
    def fetchone(self):
        return None


def _fake_db():
    return _FakeConn()


# Patch database imports
sys.modules["database"] = MagicMock(
    db=_fake_db,
    ensure_user=_fake_ensure_user,
    get_user=_fake_get_user,
    update_user=_fake_update_user,
)

# Now import the modules under test
import keyboards  # noqa: E402
from modules import onboarding  # noqa: E402
from modules.onboarding import (  # noqa: E402
    _dispatch_onboard_action,
    _handle_back,
    handle_onboard_text,
    _format_weeks_summary,
    _days_to_str,
    validate_display_name,
    validate_name,
    AWAITING_NAME,
    AWAITING_PARTNER_NAME,
)


# ── Test helpers ─────────────────────────────────────────────────────────────

def _make_query(data: str, chat_id: int = 1234):
    """Return a mock CallbackQuery."""
    q = MagicMock()
    q.data = data
    q.message = MagicMock()
    q.message.chat_id = chat_id
    q.edit_message_text = AsyncMock()
    q.edit_message_reply_markup = AsyncMock()
    q.answer = AsyncMock()
    return q


def _make_context(awaiting=None):
    """Return a mock context with user_data."""
    ctx = MagicMock()
    ctx.user_data = {"awaiting": awaiting}
    return ctx


def _make_update(text: str, chat_id: int = 1234):
    """Return a mock Update with a text message."""
    upd = MagicMock()
    upd.effective_chat = MagicMock()
    upd.effective_chat.id = chat_id
    upd.message = MagicMock()
    upd.message.text = text
    upd.message.reply_text = AsyncMock()
    return upd


def _run(coro):
    """Run an async coroutine in the test suite."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _reset_stores(chat_id=1234):
    _USERS_STORE.clear()
    _SHIFTS_STORE.clear()
    _PARTNERS_STORE.clear()
    _fake_ensure_user(chat_id, "TestUser")


# ═════════════════════════════════════════════════════════════════════════════
# TEST CASES
# ═════════════════════════════════════════════════════════════════════════════

class TestScheduleDisplayHelpers(unittest.TestCase):
    """Unit tests for the Sun-Sat display helpers."""

    def test_days_to_str_sun_first(self):
        # Sun=6, Mon=0, Fri=4 — display order must be Sun, Mon, Fri
        result = _days_to_str([0, 4, 6])
        self.assertEqual(result, "Sun, Mon, Fri")

    def test_days_to_str_empty(self):
        result = _days_to_str([])
        self.assertEqual(result, "")

    def test_days_to_str_all_seven(self):
        result = _days_to_str([0, 1, 2, 3, 4, 5, 6])
        # Sun(6) first
        self.assertTrue(result.startswith("Sun,"))
        self.assertIn("Sat", result)

    def test_format_weeks_summary_one_week(self):
        summary = _format_weeks_summary([[6, 0, 1]])
        self.assertIn("Week 1", summary)
        self.assertIn("Sun", summary)

    def test_format_weeks_summary_two_weeks(self):
        summary = _format_weeks_summary([[6, 0, 1], [3, 4]])
        self.assertIn("Week 1", summary)
        self.assertIn("Week 2", summary)
        self.assertIn("Thu", summary)

    def test_format_weeks_summary_empty(self):
        result = _format_weeks_summary([])
        self.assertIn("no days", result)


class TestInputValidation(unittest.TestCase):
    """Unit tests for name/input validation."""

    def test_valid_name(self):
        ok, result = validate_display_name("Alex")
        self.assertTrue(ok)
        self.assertEqual(result, "Alex")

    def test_empty_name(self):
        ok, _ = validate_display_name("")
        self.assertFalse(ok)

    def test_numbers_only_name(self):
        ok, _ = validate_display_name("12345")
        self.assertFalse(ok)

    def test_emoji_only_name(self):
        ok, _ = validate_display_name("😀🎉")
        self.assertFalse(ok)

    def test_name_too_long(self):
        ok, _ = validate_display_name("A" * 51)
        self.assertFalse(ok)

    def test_name_with_spaces(self):
        ok, result = validate_name("John  Smith")
        self.assertTrue(ok)
        self.assertEqual(result, "John Smith")  # double space collapsed

    def test_name_with_unicode(self):
        ok, result = validate_name("José María")
        self.assertTrue(ok)


class TestDayPickerKeyboard(unittest.TestCase):
    """Verify the onboard_days_kb keyboard layout."""

    def test_single_row_of_seven(self):
        kb = keyboards.onboard_days_kb([])
        # First row should have 7 buttons
        self.assertEqual(len(kb.inline_keyboard[0]), 7)

    def test_selected_days_show_checkmark(self):
        kb = keyboards.onboard_days_kb([6, 0])  # Sun and Mon
        btn_texts = [btn.text for btn in kb.inline_keyboard[0]]
        # Sun (6) and Mon (0) should have checkmark
        self.assertTrue(any("Su" in t and "✅" in t for t in btn_texts))
        self.assertTrue(any("Mo" in t and "✅" in t for t in btn_texts))

    def test_unselected_days_show_empty_box(self):
        kb = keyboards.onboard_days_kb([])
        btn_texts = [btn.text for btn in kb.inline_keyboard[0]]
        self.assertTrue(all("⬜" in t for t in btn_texts))

    def test_sun_is_first_button(self):
        kb = keyboards.onboard_days_kb([])
        first_btn = kb.inline_keyboard[0][0]
        self.assertIn("Su", first_btn.text)
        self.assertEqual(first_btn.callback_data, "onboard:day:6")

    def test_sat_is_last_button(self):
        kb = keyboards.onboard_days_kb([])
        last_btn = kb.inline_keyboard[0][6]
        self.assertIn("Sa", last_btn.text)
        self.assertEqual(last_btn.callback_data, "onboard:day:5")

    def test_done_button_present(self):
        kb = keyboards.onboard_days_kb([])
        all_cb = [btn.callback_data
                  for row in kb.inline_keyboard for btn in row]
        self.assertIn("onboard:days_done", all_cb)

    def test_back_button_present(self):
        kb = keyboards.onboard_days_kb([])
        all_cb = [btn.callback_data
                  for row in kb.inline_keyboard for btn in row]
        self.assertIn("onboard:back:shift_type", all_cb)

    def test_week_label_param_accepted(self):
        """week_label parameter must be accepted without error."""
        kb = keyboards.onboard_days_kb([], week_label="Week 2")
        self.assertIsNotNone(kb)


class TestHappyPathFlow(unittest.TestCase):
    """Test 1: Full happy path — name → shift → week1 → no week2 → partners → type → bills → finish."""

    def setUp(self):
        _reset_stores()

    def test_01_name_entry(self):
        """User types their name."""
        ctx = _make_context(awaiting=AWAITING_NAME)
        upd = _make_update("Alex")
        result = _run(handle_onboard_text(upd, ctx))
        self.assertTrue(result)
        user = _fake_get_user(1234)
        self.assertEqual(user["display_name"], "Alex")
        self.assertEqual(user["onboard_step"], "shift_type")

    def test_02_shift_selection(self):
        """User picks a shift type."""
        _fake_update_user(1234, onboard_step="shift_type", display_name="Alex")
        ctx = _make_context()
        query = _make_query("onboard:shift:7p-7a")
        parts = ["onboard", "shift", "7p-7a"]
        _run(_dispatch_onboard_action(query, 1234, "shift", parts, ctx))
        user = _fake_get_user(1234)
        ob = json.loads(user["onboard_data"])
        self.assertEqual(ob["shift_type"], "7p-7a")
        query.edit_message_text.assert_awaited_once()

    def test_03_day_toggle(self):
        """User toggles days on the picker."""
        _fake_update_user(1234, onboard_step="shift_days",
                          onboard_data=json.dumps({"shift_type": "7p-7a"}))
        ctx = _make_context()
        query = _make_query("onboard:day:6")
        _run(_dispatch_onboard_action(query, 1234, "day", ["onboard", "day", "6"], ctx))
        user = _fake_get_user(1234)
        ob = json.loads(user["onboard_data"])
        self.assertIn(6, ob["selected_days"])

    def test_04_days_done_asks_add_week(self):
        """After Done, bot asks 'Add Week 2?'"""
        ob = {"shift_type": "7p-7a", "selected_days": [6, 0, 1]}
        _fake_update_user(1234, onboard_step="shift_days",
                          onboard_data=json.dumps(ob))
        ctx = _make_context()
        query = _make_query("onboard:days_done")
        _run(_dispatch_onboard_action(query, 1234, "days_done",
                                      ["onboard", "days_done"], ctx))
        user = _fake_get_user(1234)
        ob_after = json.loads(user["onboard_data"])
        # weeks list should now have one entry
        self.assertEqual(len(ob_after["weeks"]), 1)
        self.assertEqual(ob_after["weeks"][0], sorted([6, 0, 1]))
        # selected_days cleared
        self.assertEqual(ob_after.get("selected_days", []), [])
        query.edit_message_text.assert_awaited_once()
        # Message should mention "Add Week 2"
        call_text = query.edit_message_text.call_args[0][0]
        self.assertIn("Week 2", call_text)

    def test_05_no_week2_saves_shift_and_advances(self):
        """Answering No to week2 saves shifts and moves to partners_intro."""
        # Note: days_done always stores sorted lists, so simulate that here
        # sorted([6, 0, 1]) = [0, 1, 6]
        sorted_days = sorted([6, 0, 1])  # [0, 1, 6]
        ob = {
            "shift_type": "7p-7a",
            "weeks": [sorted_days],
            "selected_days": [],
        }
        _fake_update_user(1234, onboard_data=json.dumps(ob))
        ctx = _make_context()
        query = _make_query("onboard:add_week:no")
        _run(_dispatch_onboard_action(query, 1234, "add_week",
                                      ["onboard", "add_week", "no"], ctx))
        # Shift should be in the fake DB
        self.assertIn(1234, _SHIFTS_STORE)
        shift = _SHIFTS_STORE[1234]
        self.assertEqual(shift["week1_days"], sorted_days)
        # week2 = same as week1 when no rotation
        self.assertEqual(shift["week2_days"], sorted_days)
        user = _fake_get_user(1234)
        self.assertEqual(user["onboard_step"], "partners_intro")
        # Confirmation message should show days in Sun-Sat order
        call_text = query.edit_message_text.call_args[0][0]
        self.assertIn("Sun", call_text)  # Sun(6) in the selected days

    def test_06_add_partner_yes(self):
        """Clicking yes to add partners prompts for name."""
        _fake_update_user(1234, onboard_step="partners_intro",
                          onboard_data=json.dumps({}))
        ctx = _make_context()
        query = _make_query("onboard:add_partners:yes")
        _run(_dispatch_onboard_action(query, 1234, "add_partners",
                                      ["onboard", "add_partners", "yes"], ctx))
        self.assertEqual(ctx.user_data["awaiting"], AWAITING_PARTNER_NAME)

    def test_07_partner_name_saved_shows_type_picker(self):
        """After typing a partner name, bot shows the relationship type picker."""
        _fake_update_user(1234, onboard_step="partner_name",
                          onboard_data=json.dumps({}))
        ctx = _make_context(awaiting=AWAITING_PARTNER_NAME)
        upd = _make_update("Sam")
        _run(handle_onboard_text(upd, ctx))
        # Partner should be in the store
        names = [p["name"] for p in _PARTNERS_STORE]
        self.assertIn("Sam", names)
        # ob_data should have pending_partner_id
        user = _fake_get_user(1234)
        ob = json.loads(user["onboard_data"])
        self.assertIn("pending_partner_id", ob)
        # Reply should ask about relationship type
        call_text = upd.message.reply_text.call_args[0][0]
        self.assertIn("relationship", call_text.lower())

    def test_08_partner_type_saved_asks_another(self):
        """partner_type handler saves type and asks 'another?'"""
        partner = _PARTNERS_STORE[0] if _PARTNERS_STORE else None
        if not partner:
            # Create one manually for this test
            _PARTNERS_STORE.append({"id": 99, "name": "Sam",
                                    "chat_id": 1234, "relationship_type": None})
            partner = _PARTNERS_STORE[-1]

        ob = {"pending_partner_id": partner["id"]}
        _fake_update_user(1234, onboard_data=json.dumps(ob))
        ctx = _make_context()
        query = _make_query("onboard:partner_type:partner")
        _run(_dispatch_onboard_action(query, 1234, "partner_type",
                                      ["onboard", "partner_type", "partner"], ctx))
        # relationship_type should be set
        self.assertEqual(partner["relationship_type"], "partner")
        # pending_partner_id removed
        user = _fake_get_user(1234)
        ob_after = json.loads(user["onboard_data"])
        self.assertNotIn("pending_partner_id", ob_after)
        # Message asks another?
        call_text = query.edit_message_text.call_args[0][0]
        self.assertIn("Another", call_text)

    def test_09_finish_onboarding(self):
        """Finish action marks user as onboarded."""
        ctx = _make_context()
        query = _make_query("onboard:finish")
        _run(_dispatch_onboard_action(query, 1234, "finish",
                                      ["onboard", "finish"], ctx))
        user = _fake_get_user(1234)
        self.assertEqual(user["onboarded"], 1)


class TestBackNavigation(unittest.TestCase):
    """Test 2: Back button navigation — must reset correct ob_data keys."""

    def setUp(self):
        _reset_stores()

    def test_back_to_shift_type_clears_week_data(self):
        """Back to shift_type must clear weeks, week1_days, week2_days, selected_days."""
        ob = {
            "shift_type": "7p-7a",
            "weeks": [[6, 0, 1]],
            "week1_days": [6, 0, 1],
            "week2_days": [6, 0, 1],
            "selected_days": [3],
        }
        _fake_update_user(1234, onboard_data=json.dumps(ob),
                          onboard_step="shift_days", display_name="Alex")
        ctx = _make_context()
        query = _make_query("onboard:back:shift_type")
        _run(_dispatch_onboard_action(query, 1234, "back",
                                      ["onboard", "back", "shift_type"], ctx))
        user = _fake_get_user(1234)
        ob_after = json.loads(user["onboard_data"])
        self.assertNotIn("weeks", ob_after)
        self.assertNotIn("week1_days", ob_after)
        self.assertNotIn("week2_days", ob_after)
        self.assertNotIn("selected_days", ob_after)
        self.assertNotIn("shift_type", ob_after)
        self.assertEqual(user["onboard_step"], "shift_type")

    def test_back_to_shift_type_then_re_enter_is_fresh(self):
        """After back→shift_type, picking days again starts with empty weeks."""
        ob = {
            "shift_type": "7p-7a",
            "weeks": [[6, 0, 1]],
            "week1_days": [6, 0, 1],
            "week2_days": [6, 0, 1],
        }
        _fake_update_user(1234, onboard_data=json.dumps(ob),
                          onboard_step="shift_days", display_name="Alex")
        ctx = _make_context()
        query = _make_query("onboard:back:shift_type")
        _run(_dispatch_onboard_action(query, 1234, "back",
                                      ["onboard", "back", "shift_type"], ctx))

        # Now pick a shift again
        query2 = _make_query("onboard:shift:7a-7p")
        _run(_dispatch_onboard_action(query2, 1234, "shift",
                                      ["onboard", "shift", "7a-7p"], ctx))

        # Toggle a day
        ob_mid = json.loads(_fake_get_user(1234)["onboard_data"])
        self.assertEqual(ob_mid.get("weeks", []), [])  # weeks is gone / empty

    def test_back_to_name_from_shift_type(self):
        """Back to name screen works."""
        _fake_update_user(1234, onboard_step="shift_type", display_name="Alex")
        ctx = _make_context()
        query = _make_query("onboard:back:name")
        _run(_dispatch_onboard_action(query, 1234, "back",
                                      ["onboard", "back", "name"], ctx))
        user = _fake_get_user(1234)
        self.assertEqual(user["onboard_step"], "name")
        self.assertEqual(ctx.user_data["awaiting"], AWAITING_NAME)

    def test_back_does_not_loop_from_schedule_confirmation(self):
        """Back from schedule confirmation goes to partners_intro, not shift_days."""
        ctx = _make_context()
        query = _make_query("onboard:back:schedule_result")
        _run(_dispatch_onboard_action(query, 1234, "back",
                                      ["onboard", "back", "schedule_result"], ctx))
        user = _fake_get_user(1234)
        self.assertEqual(user["onboard_step"], "partners_intro")


class TestMultiWeekRotation(unittest.TestCase):
    """Test 3: Multi-week schedule (week1 → yes → week2 → yes → week3 → done)."""

    def setUp(self):
        _reset_stores()
        _fake_update_user(1234, onboard_step="shift_days",
                          onboard_data=json.dumps({"shift_type": "7p-7a"}))

    def _do_days_done(self, days: list[int]):
        ob = json.loads(_fake_get_user(1234)["onboard_data"])
        ob["selected_days"] = days
        _fake_update_user(1234, onboard_data=json.dumps(ob))
        ctx = _make_context()
        query = _make_query("onboard:days_done")
        _run(_dispatch_onboard_action(query, 1234, "days_done",
                                      ["onboard", "days_done"], ctx))
        return query

    def _answer_add_week(self, yes_no: str):
        ctx = _make_context()
        query = _make_query(f"onboard:add_week:{yes_no}")
        _run(_dispatch_onboard_action(query, 1234, "add_week",
                                      ["onboard", "add_week", yes_no], ctx))
        return query

    def test_three_week_rotation(self):
        """Three weeks can be added and saved correctly."""
        # Week 1
        q1 = self._do_days_done([6, 0, 1])
        ob = json.loads(_fake_get_user(1234)["onboard_data"])
        self.assertEqual(len(ob["weeks"]), 1)

        # Say yes to week 2
        self._answer_add_week("yes")

        # Week 2
        q2 = self._do_days_done([2, 3, 4])
        ob = json.loads(_fake_get_user(1234)["onboard_data"])
        self.assertEqual(len(ob["weeks"]), 2)

        # Say yes to week 3
        self._answer_add_week("yes")

        # Week 3
        q3 = self._do_days_done([5])
        ob = json.loads(_fake_get_user(1234)["onboard_data"])
        self.assertEqual(len(ob["weeks"]), 3)

        # Say no (done)
        self._answer_add_week("no")

        # Shift should be saved (week1 + week2 in DB for back-compat)
        self.assertIn(1234, _SHIFTS_STORE)
        shift = _SHIFTS_STORE[1234]
        self.assertEqual(shift["week1_days"], sorted([6, 0, 1]))
        self.assertEqual(shift["week2_days"], sorted([2, 3, 4]))

    def test_week2_message_shows_week_number(self):
        """After week1 done, bot asks about Week 2 (not just 'another week')."""
        q = self._do_days_done([6, 0])
        call_text = q.edit_message_text.call_args[0][0]
        self.assertIn("Week 2", call_text)

    def test_weeks_summary_shows_sun_sat_order(self):
        """Schedule confirmation shows days in Sun-Sat order."""
        ob = {
            "shift_type": "7p-7a",
            "weeks": [[0, 6]],  # Mon and Sun, stored unsorted
            "selected_days": [],
        }
        _fake_update_user(1234, onboard_data=json.dumps(ob))
        ctx = _make_context()
        query = _make_query("onboard:add_week:no")
        _run(_dispatch_onboard_action(query, 1234, "add_week",
                                      ["onboard", "add_week", "no"], ctx))
        call_text = query.edit_message_text.call_args[0][0]
        # Sun must appear before Mon in the text
        sun_pos = call_text.find("Sun")
        mon_pos = call_text.find("Mon")
        self.assertGreater(sun_pos, -1)
        self.assertGreater(mon_pos, -1)
        self.assertLess(sun_pos, mon_pos)


class TestBadInputs(unittest.TestCase):
    """Test 4: Bad/edge-case text inputs."""

    def test_empty_name_rejected(self):
        ok, _ = validate_display_name("")
        self.assertFalse(ok)

    def test_numbers_only_rejected(self):
        ok, _ = validate_display_name("99999")
        self.assertFalse(ok)

    def test_emoji_only_rejected(self):
        ok, _ = validate_display_name("🎉🔥💯")
        self.assertFalse(ok)

    def test_whitespace_only_rejected(self):
        ok, _ = validate_display_name("   ")
        self.assertFalse(ok)

    def test_valid_unicode_name_accepted(self):
        ok, _ = validate_display_name("Ólafur")
        self.assertTrue(ok)

    def test_no_days_selected_rejected(self):
        """Tapping Done with no days selected shows alert, no state change."""
        _reset_stores()
        ob = {"shift_type": "7p-7a", "selected_days": [], "weeks": []}
        _fake_update_user(1234, onboard_data=json.dumps(ob))
        ctx = _make_context()
        query = _make_query("onboard:days_done")
        _run(_dispatch_onboard_action(query, 1234, "days_done",
                                      ["onboard", "days_done"], ctx))
        # answer called with show_alert=True
        query.answer.assert_awaited_once()
        call_kwargs = query.answer.call_args[1]
        self.assertTrue(call_kwargs.get("show_alert", False))
        # No edit should happen
        query.edit_message_text.assert_not_awaited()


class TestRepeatBackForward(unittest.TestCase):
    """Test 5: Back/forward/back/forward/back (5 times) without breaking."""

    def setUp(self):
        _reset_stores()
        _fake_update_user(1234, display_name="Alex",
                          onboard_step="shift_type", onboard_data=json.dumps({}))

    def test_five_back_forward_cycles(self):
        """User toggles between name and shift_type five times, no crash."""
        for _ in range(5):
            ctx = _make_context()
            # Go back to name
            q_back = _make_query("onboard:back:name")
            _run(_dispatch_onboard_action(q_back, 1234, "back",
                                          ["onboard", "back", "name"], ctx))
            self.assertEqual(_fake_get_user(1234)["onboard_step"], "name")

            # Name text entry
            ctx2 = _make_context(awaiting=AWAITING_NAME)
            upd = _make_update("Alex")
            _run(handle_onboard_text(upd, ctx2))
            self.assertEqual(_fake_get_user(1234)["onboard_step"], "shift_type")


class TestRerunOnboarding(unittest.TestCase):
    """Test 6: Re-run onboarding (user already onboarded)."""

    def setUp(self):
        _reset_stores()
        _fake_update_user(1234, onboarded=1, onboard_step=None,
                          display_name="Alex",
                          onboard_data=json.dumps({"shift_type": "7p-7a",
                                                   "week1_days": [6, 0, 1],
                                                   "week2_days": [6, 0, 1]}))

    def test_start_resets_state(self):
        """Sending 'onboard:start' resets onboarded flag and clears onboard_data."""
        ctx = _make_context()
        query = _make_query("onboard:start")
        _run(_dispatch_onboard_action(query, 1234, "start",
                                      ["onboard", "start"], ctx))
        user = _fake_get_user(1234)
        self.assertEqual(user["onboarded"], 0)
        self.assertEqual(user["onboard_step"], "name")
        self.assertEqual(json.loads(user["onboard_data"]), {})
        self.assertEqual(ctx.user_data["awaiting"], AWAITING_NAME)

    def test_full_rerun_flow(self):
        """After reset, full flow works as if user is new."""
        ctx = _make_context()
        query = _make_query("onboard:start")
        _run(_dispatch_onboard_action(query, 1234, "start",
                                      ["onboard", "start"], ctx))

        # Name
        ctx2 = _make_context(awaiting=AWAITING_NAME)
        upd = _make_update("Alex Again")
        _run(handle_onboard_text(upd, ctx2))
        self.assertEqual(_fake_get_user(1234)["display_name"], "Alex Again")

        # Shift
        query2 = _make_query("onboard:shift:7a-7p")
        _run(_dispatch_onboard_action(query2, 1234, "shift",
                                      ["onboard", "shift", "7a-7p"], ctx2))
        ob = json.loads(_fake_get_user(1234)["onboard_data"])
        self.assertEqual(ob["shift_type"], "7a-7p")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
