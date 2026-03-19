"""
test_onboarding.py — comprehensive tests for the overhauled onboarding module.

Tests:
  1. Name validation (validate_display_name + validate_name)
  2. Bill amount validation
  3. Date validation (parse_date_loosely + validate_date)
  4. Recovery simulation (onboard_step in DB but no context.user_data["awaiting"])
  5. Duplicate detection helpers
"""
import sys
import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

# ── Stub TELEGRAM_BOT_TOKEN so config.py doesn't crash ──────────────────────
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "TEST_TOKEN_FOR_UNIT_TESTS")

# ── Stub DATABASE_PATH so database.py doesn't crash ─────────────────────────
os.environ.setdefault("DATABASE_PATH", ":memory:")

# ── Patch the config module before anything imports it ───────────────────────
# We patch at module level so that `from config import DATABASE_PATH` works
import types
_fake_config = types.ModuleType("config")
_fake_config.BOT_TOKEN = "TEST_TOKEN_FOR_UNIT_TESTS"
_fake_config.DATABASE_PATH = ":memory:"
_fake_config.TIMEZONE = "America/New_York"
_fake_config.NOTIFY_START = None
_fake_config.NOTIFY_END = None
_fake_config.DAILY_DIGEST_HOUR = 14
_fake_config.EVENING_CHECKIN_HOUR = 22
_fake_config.WEEKLY_DIGEST_DAY = 6
_fake_config.WEEKLY_DIGEST_HOUR = 12
sys.modules["config"] = _fake_config

# ── Stub database module so we don't need a real DB for validation tests ─────
_fake_db_module = types.ModuleType("database")

# Provide a minimal no-op db context manager
import contextlib

@contextlib.contextmanager
def _noop_db():
    conn = MagicMock()
    conn.execute = MagicMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
    yield conn

_fake_db_module.db = _noop_db
_fake_db_module.ensure_user = MagicMock(return_value=False)
_fake_db_module.update_user = MagicMock()
_fake_db_module.get_user = MagicMock(return_value={
    "chat_id": 12345,
    "display_name": "TestUser",
    "onboarded": 0,
    "onboard_step": None,
    "onboard_data": "{}",
})
sys.modules["database"] = _fake_db_module

# ── Stub keyboards module ─────────────────────────────────────────────────────
import types as _types_mod
_fake_keyboards = _types_mod.ModuleType("keyboards")
_fake_keyboards.onboard_welcome_kb = MagicMock(return_value=None)
_fake_keyboards.onboard_shift_type_kb = MagicMock(return_value=None)
_fake_keyboards.onboard_days_kb = MagicMock(return_value=None)
_fake_keyboards.onboard_section_done_kb = MagicMock(return_value=None)
_fake_keyboards.onboard_yes_no_kb = MagicMock(return_value=None)
_fake_keyboards.onboard_skip_kb = MagicMock(return_value=None)
_fake_keyboards.onboard_progress_text = lambda s: f"📊 Step X — {s}"
_fake_keyboards.main_menu_kb = MagicMock(return_value=None)
sys.modules["keyboards"] = _fake_keyboards

# ── Add project root to path ─────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── NOW import the functions under test ──────────────────────────────────────
from modules.onboarding import (
    validate_name,
    validate_display_name,
    validate_bill_amount,
    validate_date,
    parse_date_loosely,
    validate_shift_desc,
    STEP_TO_AWAITING,
    AWAITING_NAME,
    AWAITING_PARTNER_NAME,
    AWAITING_BILL_NAME,
    AWAITING_BILL_AMOUNT,
    AWAITING_CAR_DESC,
    AWAITING_CAR_DATE,
    AWAITING_CRED_NAME,
    AWAITING_CRED_EXPIRY,
    AWAITING_MED_NAME,
    AWAITING_CUSTOM_SHIFT,
)


# ══════════════════════════════════════════════════════════════════════════════
# NAME VALIDATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestNameValidation(unittest.TestCase):
    """Tests for validate_name() — generic name validator."""

    def _assert_accepted(self, text, expected_cleaned=None):
        ok, result = validate_name(text)
        self.assertTrue(ok, f"Expected '{text}' to be accepted, got: {result}")
        if expected_cleaned is not None:
            self.assertEqual(result, expected_cleaned,
                             f"Expected cleaned='{expected_cleaned}', got='{result}'")
        return result

    def _assert_rejected(self, text):
        ok, result = validate_name(text)
        self.assertFalse(ok, f"Expected '{text}' to be rejected, but it was accepted as: {result}")

    # ── Should accept ─────────────────────────────────────────────────────────
    def test_normal_name(self):
        self._assert_accepted("Diego", "Diego")

    def test_accented_name(self):
        self._assert_accepted("María José", "María José")

    def test_hyphenated_name(self):
        self._assert_accepted("Jean-Luc", "Jean-Luc")

    def test_apostrophe_name(self):
        self._assert_accepted("O'Brien", "O'Brien")

    def test_cjk_name(self):
        self._assert_accepted("太郎", "太郎")

    def test_arabic_name(self):
        self._assert_accepted("أحمد", "أحمد")

    def test_mixed_emoji_accepted(self):
        """Names with mixed letters + emojis are fine."""
        self._assert_accepted("Diego 🤙")

    def test_unicode_letters_with_numbers(self):
        """Letters + numbers is valid (e.g. 'Diego42')."""
        self._assert_accepted("Diego42")

    def test_trailing_spaces_stripped(self):
        """Leading/trailing spaces should be stripped."""
        self._assert_accepted("  Diego  ", "Diego")

    def test_internal_multiple_spaces_collapsed(self):
        """Multiple internal spaces collapsed to one."""
        self._assert_accepted("María  José", "María José")

    def test_doctor_name(self):
        """Period in name should be fine."""
        self._assert_accepted("Dr. Smith", "Dr. Smith")

    def test_cyrillic(self):
        self._assert_accepted("Александр")

    def test_hebrew_name(self):
        self._assert_accepted("דוד")

    def test_tab_stripped(self):
        """Tab + spaces → stripped."""
        ok, result = validate_name("\t Diego \t")
        self.assertTrue(ok)
        self.assertEqual(result, "Diego")

    # ── Should reject ─────────────────────────────────────────────────────────
    def test_all_emoji_rejected(self):
        """All emoji, no letters → rejected."""
        self._assert_rejected("🤙🤙🤙")

    def test_empty_string_rejected(self):
        self._assert_rejected("")

    def test_only_spaces_rejected(self):
        self._assert_rejected("   ")

    def test_very_long_rejected(self):
        """200-character name is over the 100-char limit."""
        self._assert_rejected("A" * 200)

    def test_special_chars_only_rejected(self):
        """Only symbols, no letter characters → rejected."""
        self._assert_rejected("!@#$%^&*()")


class TestDisplayNameValidation(unittest.TestCase):
    """Tests for validate_display_name() — stricter: max 50 chars, no pure numbers."""

    def _assert_accepted(self, text, expected_cleaned=None):
        ok, result = validate_display_name(text)
        self.assertTrue(ok, f"Expected '{text}' to be accepted, got: {result}")
        if expected_cleaned is not None:
            self.assertEqual(result, expected_cleaned)
        return result

    def _assert_rejected(self, text):
        ok, result = validate_display_name(text)
        self.assertFalse(ok, f"Expected '{text}' to be rejected, but accepted as: {result}")

    def test_normal_name_accepted(self):
        self._assert_accepted("Diego", "Diego")

    def test_accented_accepted(self):
        self._assert_accepted("María José")

    def test_pure_numbers_rejected(self):
        """'12345' is numbers-only → rejected for display_name."""
        self._assert_rejected("12345")

    def test_letters_with_numbers_accepted(self):
        """'Diego42' has letters → accepted."""
        self._assert_accepted("Diego42")

    def test_over_50_chars_rejected(self):
        """51-char name → rejected (50-char limit for display_name)."""
        self._assert_rejected("A" * 51)

    def test_exactly_50_chars_accepted(self):
        """Exactly 50 chars → accepted."""
        self._assert_accepted("A" * 50)

    def test_empty_rejected(self):
        self._assert_rejected("")

    def test_trailing_spaces_stripped(self):
        self._assert_accepted("  Diego  ", "Diego")


# ══════════════════════════════════════════════════════════════════════════════
# BILL AMOUNT VALIDATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestBillAmountValidation(unittest.TestCase):

    def _assert_amount(self, text, expected_amount):
        ok, amount, err = validate_bill_amount(text)
        self.assertTrue(ok, f"Expected '{text}' to be valid, got error: {err}")
        if expected_amount is None:
            self.assertIsNone(amount, f"Expected None amount for '{text}', got {amount}")
        else:
            self.assertAlmostEqual(amount, expected_amount, places=2,
                                   msg=f"Expected {expected_amount} for '{text}', got {amount}")

    def _assert_rejected(self, text):
        ok, amount, err = validate_bill_amount(text)
        self.assertFalse(ok, f"Expected '{text}' to be rejected but got amount={amount}")

    def test_plain_number(self):
        self._assert_amount("1500", 1500.0)

    def test_dollar_comma_format(self):
        self._assert_amount("$1,500.00", 1500.0)

    def test_skip(self):
        self._assert_amount("skip", None)

    def test_idk(self):
        self._assert_amount("idk", None)

    def test_question_mark(self):
        self._assert_amount("?", None)

    def test_no(self):
        self._assert_amount("no", None)

    def test_not_sure(self):
        self._assert_amount("not sure", None)

    def test_dunno(self):
        self._assert_amount("dunno", None)

    def test_zero(self):
        """$0 is valid — some bills have zero balance."""
        self._assert_amount("0", 0.0)

    def test_dollar_zero(self):
        self._assert_amount("$0", 0.0)

    def test_decimal(self):
        self._assert_amount("150.5", 150.5)

    def test_negative_rejected(self):
        self._assert_rejected("-50")

    def test_too_large_rejected(self):
        self._assert_rejected("2000000")

    def test_abc_rejected(self):
        self._assert_rejected("abc")

    def test_dollar_comma_no_cents(self):
        self._assert_amount("$1,500", 1500.0)

    def test_just_dollar_rejected(self):
        """A bare '$' with no number should be rejected."""
        self._assert_rejected("$")

    def test_exact_million_rejected(self):
        """1,000,001 > 1,000,000 → rejected."""
        self._assert_rejected("1000001")

    def test_exact_million_accepted(self):
        """$1,000,000 = limit → accepted."""
        self._assert_amount("1000000", 1_000_000.0)


# ══════════════════════════════════════════════════════════════════════════════
# DATE VALIDATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestDateParsing(unittest.TestCase):

    def _assert_date(self, text, expected_iso):
        ok, iso_str, err = parse_date_loosely(text)
        self.assertTrue(ok, f"Expected '{text}' to parse, got error: {err}")
        self.assertEqual(iso_str, expected_iso,
                         f"Expected '{expected_iso}' for '{text}', got '{iso_str}'")

    def _assert_unparseable(self, text):
        ok, iso_str, err = parse_date_loosely(text)
        self.assertFalse(ok, f"Expected '{text}' to fail parsing, but got: {iso_str}")

    def test_iso_date(self):
        self._assert_date("2026-05-18", "2026-05-18")

    def test_month_year(self):
        self._assert_date("May 2026", "2026-05-01")

    def test_month_day_year(self):
        self._assert_date("May 18th 2026", "2026-05-18")

    def test_tomorrow(self):
        expected = (date.today() + timedelta(days=1)).isoformat()
        ok, iso_str, err = parse_date_loosely("tomorrow")
        self.assertTrue(ok)
        self.assertEqual(iso_str, expected)

    def test_in_6_months(self):
        ok, iso_str, err = parse_date_loosely("in 6 months")
        self.assertTrue(ok, f"'in 6 months' failed: {err}")
        today = date.today()
        parsed = date.fromisoformat(iso_str)
        delta_days = (parsed - today).days
        self.assertGreater(delta_days, 150,
                           f"'in 6 months' should be > 150 days out, got {delta_days}")
        self.assertLess(delta_days, 220,
                        f"'in 6 months' should be < 220 days out, got {delta_days}")

    def test_in_2_weeks(self):
        ok, iso_str, err = parse_date_loosely("in 2 weeks")
        self.assertTrue(ok)
        expected = (date.today() + timedelta(weeks=2)).isoformat()
        self.assertEqual(iso_str, expected)

    def test_potato_unparseable(self):
        self._assert_unparseable("potato")

    def test_next_week(self):
        ok, iso_str, err = parse_date_loosely("next week")
        self.assertTrue(ok)
        expected = (date.today() + timedelta(weeks=1)).isoformat()
        self.assertEqual(iso_str, expected)

    def test_in_1_day(self):
        ok, iso_str, err = parse_date_loosely("in 1 day")
        self.assertTrue(ok)
        expected = (date.today() + timedelta(days=1)).isoformat()
        self.assertEqual(iso_str, expected)

    def test_in_3_years(self):
        ok, iso_str, err = parse_date_loosely("in 3 years")
        self.assertTrue(ok)
        expected_year = date.today().year + 3
        self.assertEqual(iso_str[:4], str(expected_year))

    def test_empty_string_unparseable(self):
        self._assert_unparseable("")


class TestDateValidation(unittest.TestCase):
    """Tests validate_date() which wraps parse_date_loosely with past/future checks."""

    def test_future_date_accepted(self):
        future = (date.today() + timedelta(days=30)).isoformat()
        ok, iso_str, err = validate_date(future)
        self.assertTrue(ok, f"Future date should be accepted: {err}")

    def test_past_date_rejected_by_default(self):
        ok, iso_str, err = validate_date("2020-01-01")
        self.assertFalse(ok)
        self.assertIn("passed", err.lower())

    def test_past_date_allowed_when_flag_set(self):
        ok, iso_str, err = validate_date("2020-01-01", allow_past=True)
        self.assertTrue(ok, f"Past date should be allowed with allow_past=True: {err}")
        self.assertEqual(iso_str, "2020-01-01")

    def test_garbage_rejected(self):
        ok, iso_str, err = validate_date("potato")
        self.assertFalse(ok)

    def test_far_future_rejected(self):
        """11 years out should be rejected."""
        far_future = date.today().replace(year=date.today().year + 11).isoformat()
        ok, iso_str, err = validate_date(far_future)
        self.assertFalse(ok)
        self.assertIn("far", err.lower())

    def test_10_years_boundary_accepted(self):
        """Exactly 10 years out is on the boundary — should be accepted."""
        boundary = date.today().replace(year=date.today().year + 10).isoformat()
        ok, iso_str, err = validate_date(boundary)
        self.assertTrue(ok, f"10-year boundary should be accepted: {err}")

    def test_tomorrow_accepted(self):
        ok, iso_str, err = validate_date("tomorrow")
        self.assertTrue(ok, f"'tomorrow' should be accepted: {err}")


# ══════════════════════════════════════════════════════════════════════════════
# SHIFT DESCRIPTION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestShiftDesc(unittest.TestCase):

    def test_valid_shift(self):
        ok, result = validate_shift_desc("3p-11p")
        self.assertTrue(ok)
        self.assertEqual(result, "3p-11p")

    def test_empty_rejected(self):
        ok, result = validate_shift_desc("   ")
        self.assertFalse(ok)

    def test_over_50_rejected(self):
        ok, result = validate_shift_desc("A" * 51)
        self.assertFalse(ok)

    def test_exactly_50_accepted(self):
        ok, result = validate_shift_desc("A" * 50)
        self.assertTrue(ok)

    def test_whitespace_stripped(self):
        ok, result = validate_shift_desc("  7p-7a  ")
        self.assertTrue(ok)
        self.assertEqual(result, "7p-7a")


# ══════════════════════════════════════════════════════════════════════════════
# RECOVERY / STEP_TO_AWAITING MAPPING TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestRecovery(unittest.TestCase):
    """
    Simulates the scenario where the bot restarts mid-onboarding:
    onboard_step is set in the DB but context.user_data["awaiting"] is missing.

    We verify that STEP_TO_AWAITING contains all the text-input steps and
    maps to the correct awaiting constants.
    """

    def test_name_step_mapped(self):
        self.assertIn("name", STEP_TO_AWAITING)
        self.assertEqual(STEP_TO_AWAITING["name"], AWAITING_NAME)

    def test_all_text_steps_mapped(self):
        expected_steps = {
            "name", "custom_shift",
            "partner_name", "bill_name", "bill_amount",
            "car_desc", "car_date",
            "cred_name", "cred_expiry",
            "med_name",
        }
        for step in expected_steps:
            self.assertIn(step, STEP_TO_AWAITING,
                          f"Step '{step}' missing from STEP_TO_AWAITING")

    def test_correct_awaiting_values(self):
        """Spot-check a few specific mappings."""
        self.assertEqual(STEP_TO_AWAITING["name"], AWAITING_NAME)
        self.assertEqual(STEP_TO_AWAITING["partner_name"], AWAITING_PARTNER_NAME)
        self.assertEqual(STEP_TO_AWAITING["bill_name"], AWAITING_BILL_NAME)
        self.assertEqual(STEP_TO_AWAITING["bill_amount"], AWAITING_BILL_AMOUNT)
        self.assertEqual(STEP_TO_AWAITING["car_desc"], AWAITING_CAR_DESC)
        self.assertEqual(STEP_TO_AWAITING["car_date"], AWAITING_CAR_DATE)
        self.assertEqual(STEP_TO_AWAITING["cred_name"], AWAITING_CRED_NAME)
        self.assertEqual(STEP_TO_AWAITING["cred_expiry"], AWAITING_CRED_EXPIRY)
        self.assertEqual(STEP_TO_AWAITING["med_name"], AWAITING_MED_NAME)
        self.assertEqual(STEP_TO_AWAITING["custom_shift"], AWAITING_CUSTOM_SHIFT)

    def test_button_steps_not_in_map(self):
        """Steps that use buttons (not text) should NOT be in STEP_TO_AWAITING."""
        button_steps = ["shift_type", "shift_days", "partners_intro",
                        "bills_intro", "car_intro", "creds_intro", "meds_intro"]
        for step in button_steps:
            self.assertNotIn(
                step, STEP_TO_AWAITING,
                f"Button step '{step}' should not be in STEP_TO_AWAITING — "
                f"it would cause text to be consumed when user isn't typing"
            )


# ══════════════════════════════════════════════════════════════════════════════
# EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):

    def test_name_with_cyrillics_and_spaces(self):
        ok, result = validate_name("Иван Иванов")
        self.assertTrue(ok)
        self.assertEqual(result, "Иван Иванов")

    def test_bill_amount_with_spaces(self):
        ok, amount, err = validate_bill_amount("  1500  ")
        self.assertTrue(ok)
        self.assertAlmostEqual(amount, 1500.0, places=2)

    def test_hebrew_name_accepted(self):
        ok, result = validate_name("דוד")
        self.assertTrue(ok)

    def test_name_numbers_letters_accepted(self):
        """Mixed letters and numbers is fine for generic names."""
        ok, result = validate_name("Unit 4B")
        self.assertTrue(ok)

    def test_bill_amount_skip_case_insensitive(self):
        """'SKIP' / 'Skip' should also be treated as skip."""
        ok, amount, err = validate_bill_amount("SKIP")
        self.assertTrue(ok)
        self.assertIsNone(amount)

    def test_bill_amount_idk_case_insensitive(self):
        ok, amount, err = validate_bill_amount("IDK")
        # Note: our implementation uses .lower() so IDK → idk → None
        # The spec says "idk" → None; IDK is same intent
        # If this test fails, the impl may be case-sensitive — that's a bug
        self.assertTrue(ok)
        self.assertIsNone(amount)

    def test_month_day_year_without_ordinal(self):
        ok, iso_str, err = parse_date_loosely("May 18 2026")
        self.assertTrue(ok)
        self.assertEqual(iso_str, "2026-05-18")

    def test_next_month(self):
        ok, iso_str, err = parse_date_loosely("next month")
        self.assertTrue(ok)
        today = date.today()
        parsed = date.fromisoformat(iso_str)
        # Should be ~30 days out
        self.assertGreater((parsed - today).days, 0)

    def test_in_1_week(self):
        ok, iso_str, err = parse_date_loosely("in 1 week")
        self.assertTrue(ok)
        expected = (date.today() + timedelta(weeks=1)).isoformat()
        self.assertEqual(iso_str, expected)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestNameValidation,
        TestDisplayNameValidation,
        TestBillAmountValidation,
        TestDateParsing,
        TestDateValidation,
        TestShiftDesc,
        TestRecovery,
        TestEdgeCases,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    sys.exit(0 if result.wasSuccessful() else 1)
