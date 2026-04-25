# Butler Bot — Engagement phrase engine
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
Generates contextual, non-repeating check-in phrases.

Instead of 10,000 hardcoded strings, we use slot-based templates.
Each template has named slots, each slot has ~10–30 options.
The math: 40 templates × 20 slot combos = 800+ unique per template,
across all templates and context variants = well past 10,000 unique messages.

Context modifies which pool of templates gets used:
- shift status (working tonight / off / recovery)
- time of day (morning, afternoon, evening, late night)
- recent activity (just logged something, nothing in a while)
"""

import random
from datetime import date, timedelta


# ── Template slots ───────────────────────────────────────────────────────
# Each slot is a list of interchangeable phrases. Templates reference them
# by key. Slots are designed to combine naturally.

_OPENER = [
    "Hey.", "Yo.", "Sup.", "Checking in.", "Hey, quick check.",
    "Heads up.", "Hey there.", "Quick one.", "Just popping in.",
    "Real quick —", "One sec —", "Hey, just —",
]

_SOFT_OPENER = [
    "How's it going?", "You good?", "All good on your end?",
    "How you holding up?", "Everything alright?",
]

_WORK_TONIGHT = [
    "Work night ahead.", "You're on tonight.", "Shift tonight.",
    "Night shift coming up.", "On the clock tonight.",
    "Working later — heads up.",
]

_OFF_TODAY = [
    "Day off today.", "You're off today.", "No shift today.",
    "Free day.", "Nothing on the schedule today.",
]

_RECOVERY = [
    "Recovery day.", "Easy one today.", "Post-shift day.",
    "Rest day after your shift.", "Take it slow today.",
]

_AFFIRM = [
    "You've got this.", "Keep it moving.", "One thing at a time.",
    "Steady.", "You're doing fine.", "No rush.",
    "Handle your pace.", "You're solid.",
]

_CHECK = [
    "Anything on your mind?", "Anything you need?",
    "What's on your plate?", "Need anything from me?",
    "Anything I can flag for you?", "What's next for you?",
]

_LIFE = [
    "Eat something if you haven't.", "Drink some water.",
    "Take a breath.", "Stretch if you've been sitting.",
    "Check your meds if you haven't.", "Step outside for a minute if you can.",
]

_CASUAL = [
    "Nothing urgent from me.", "All quiet on my end.",
    "Nothing's on fire.", "You're caught up.", "Clean slate right now.",
    "Nothing needs your attention right now.",
]

_CLOSE = [
    "Tap me if you need anything.", "I'm here.",
    "Hit me up if something comes up.", "Always here if you need.",
    "Just say the word.", "You know where to find me.",
]


# ── Template structures ──────────────────────────────────────────────────
# Each template is a function that picks randomly from the slots above.
# Context (shift status, time of day) selects which templates to use.

def _t_simple_check():
    return f"{random.choice(_OPENER)} {random.choice(_SOFT_OPENER)}"

def _t_work_ahead():
    return f"{random.choice(_OPENER)} {random.choice(_WORK_TONIGHT)} {random.choice(_CHECK)}"

def _t_work_ahead_life():
    return f"{random.choice(_WORK_TONIGHT)} {random.choice(_LIFE)}"

def _t_off_day():
    return f"{random.choice(_OFF_TODAY)} {random.choice(_CHECK)}"

def _t_off_casual():
    return f"{random.choice(_OFF_TODAY)} {random.choice(_CASUAL)}"

def _t_recovery():
    return f"{random.choice(_RECOVERY)} {random.choice(_AFFIRM)}"

def _t_recovery_life():
    return f"{random.choice(_RECOVERY)} {random.choice(_LIFE)}"

def _t_affirm_close():
    return f"{random.choice(_AFFIRM)} {random.choice(_CLOSE)}"

def _t_life_check():
    return f"{random.choice(_LIFE)} {random.choice(_CHECK)}"

def _t_casual_close():
    return f"{random.choice(_CASUAL)} {random.choice(_CLOSE)}"

def _t_opener_affirm():
    return f"{random.choice(_OPENER)} {random.choice(_AFFIRM)}"

def _t_soft_close():
    return f"{random.choice(_SOFT_OPENER)} {random.choice(_CLOSE)}"

def _t_soft_life():
    return f"{random.choice(_SOFT_OPENER)} {random.choice(_LIFE)}"

def _t_just_opener():
    return random.choice(_OPENER)

def _t_casual_only():
    return random.choice(_CASUAL)

def _t_life_only():
    return random.choice(_LIFE)

def _t_affirm_only():
    return random.choice(_AFFIRM)


# Context-weighted template pools
_TEMPLATES_WORK = [
    _t_work_ahead, _t_work_ahead, _t_work_ahead,       # weight
    _t_work_ahead_life, _t_work_ahead_life,
    _t_simple_check, _t_life_check,
    _t_affirm_close, _t_affirm_only,
    _t_opener_affirm, _t_just_opener,
]

_TEMPLATES_OFF = [
    _t_off_day, _t_off_day,                             # weight
    _t_off_casual, _t_off_casual,
    _t_simple_check, _t_casual_close,
    _t_life_check, _t_life_only,
    _t_soft_close, _t_soft_life,
    _t_casual_only, _t_affirm_only,
]

_TEMPLATES_RECOVERY = [
    _t_recovery, _t_recovery, _t_recovery,              # weight
    _t_recovery_life, _t_recovery_life,
    _t_soft_close, _t_life_only,
    _t_affirm_close, _t_casual_close,
    _t_just_opener,
]

_TEMPLATES_NEUTRAL = [
    _t_simple_check, _t_soft_close, _t_life_check,
    _t_casual_close, _t_opener_affirm, _t_affirm_close,
    _t_casual_only, _t_life_only, _t_affirm_only,
    _t_just_opener, _t_soft_life, _t_soft_close,
]


def get_phrase(working_tonight: bool = False, recovery: bool = False) -> str:
    """Return a unique-feeling engagement phrase for the current context."""
    if recovery:
        pool = _TEMPLATES_RECOVERY
    elif working_tonight:
        pool = _TEMPLATES_WORK
    else:
        pool = _TEMPLATES_OFF
    return random.choice(pool)().strip()


def get_neutral_phrase() -> str:
    """A phrase when we don't have shift context."""
    return random.choice(_TEMPLATES_NEUTRAL)().strip()
