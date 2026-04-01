#!/usr/bin/env python3
"""Patch script: applies all remaining onboarding.py changes."""
import re

with open("modules/onboarding.py", "r") as f:
    src = f.read()

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 1: Replace schedule picker block (days_done + has_week2)
# with full multi-week N-rotation support and Sun-Sat display
# ─────────────────────────────────────────────────────────────────────────────

OLD_SCHEDULE = '''\
    # ── Day Selection (multi-select) ─────────────────────────
    if action == "day":
        day_num = int(parts[2])
        selected = ob_data.get("selected_days", [])
        if day_num in selected:
            selected.remove(day_num)
        else:
            selected.append(day_num)
        ob_data["selected_days"] = selected
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        await query.edit_message_reply_markup(reply_markup=onboard_days_kb(selected))
        return

    if action == "days_done":
        selected = ob_data.get("selected_days", [])

        # Validate: at least 1 day
        if not selected:
            await query.answer(
                "You need to pick at least one day — tap the days you work.",
                show_alert=True,
            )
            return

        # Note if all 7 selected
        all_7_note = ""
        if len(selected) == 7:
            all_7_note = " Every day? Respect. 💪"

        if not ob_data.get("week1_days"):
            # First pass = week 1
            ob_data["week1_days"] = sorted(selected)
            ob_data["selected_days"] = []
            update_user(chat_id, onboard_data=json.dumps(ob_data))
            await query.edit_message_text(
                f"{all_7_note}\\nGot it. Do you have a Week 2 rotation with different days?".strip(),
                reply_markup=onboard_yes_no_kb("onboard:has_week2",
                                               back_section="shift_type"),
            )
        else:
            # Second pass = week 2
            ob_data["week2_days"] = sorted(selected)
            ob_data.pop("selected_days", None)
            update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="partners_intro")

            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO shifts (chat_id, shift_type, week1_days, week2_days) "
                    "VALUES (?, ?, ?, ?)",
                    (chat_id, ob_data.get("shift_type", "custom"),
                     json.dumps(ob_data["week1_days"]), json.dumps(ob_data["week2_days"])),
                )

            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            w1 = ", ".join(day_names[d] for d in ob_data["week1_days"])
            w2 = ", ".join(day_names[d] for d in ob_data["week2_days"])
            await query.edit_message_text(
                f"{onboard_progress_text(\'partners_intro\')}\\n\\n"
                f"Schedule saved.{all_7_note}\\n"
                f"  Week 1: {w1}\\n"
                f"  Week 2: {w2}\\n\\n"
                "Next up: people and relationships.",
                reply_markup=onboard_section_done_kb("partners_intro",
                                                     back_section="shift_type"),
            )
        return

    if action == "has_week2":
        answer = parts[2] if len(parts) > 2 else "no"

        if answer == "yes":
            ob_data["selected_days"] = []
            update_user(chat_id, onboard_data=json.dumps(ob_data))
            await query.edit_message_text(
                f"{onboard_progress_text(\'shift_days\')}\\n\\nPick your Week 2 days:",
                reply_markup=onboard_days_kb([]),
            )
        else:
            ob_data["week2_days"] = ob_data.get("week1_days", [])
            update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="partners_intro")

            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO shifts (chat_id, shift_type, week1_days, week2_days) "
                    "VALUES (?, ?, ?, ?)",
                    (chat_id, ob_data.get("shift_type", "custom"),
                     json.dumps(ob_data["week1_days"]), json.dumps(ob_data["week2_days"])),
                )

            await query.edit_message_text(
                f"{onboard_progress_text(\'partners_intro\')}\\n\\n"
                "Schedule saved — same days every week.\\n\\n"
                "Next: people and relationships.",
                reply_markup=onboard_section_done_kb("partners_intro",
                                                     back_section="shift_type"),
            )
        return'''

NEW_SCHEDULE = '''\
    # ── Day Selection (multi-select) ─────────────────────────
    if action == "day":
        day_num = int(parts[2])
        selected = ob_data.get("selected_days", [])
        if day_num in selected:
            selected.remove(day_num)
        else:
            selected.append(day_num)
        ob_data["selected_days"] = selected
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        await query.edit_message_reply_markup(reply_markup=onboard_days_kb(selected))
        return

    if action == "days_done":
        selected = ob_data.get("selected_days", [])

        # Validate: at least 1 day
        if not selected:
            await query.answer(
                "You need to pick at least one day — tap the days you work.",
                show_alert=True,
            )
            return

        # Save current week into the weeks list
        weeks = ob_data.get("weeks", [])
        weeks.append(sorted(selected))
        ob_data["weeks"] = weeks
        ob_data["selected_days"] = []
        update_user(chat_id, onboard_data=json.dumps(ob_data))

        week_num = len(weeks)
        all_7_note = " Every day? Respect. 💪" if len(selected) == 7 else ""
        week_summary = _format_weeks_summary(weeks)
        next_week_num = week_num + 1

        await query.edit_message_text(
            f"{week_summary}{all_7_note}\\n\\n"
            f"Add Week {next_week_num} to the rotation?",
            reply_markup=onboard_yes_no_kb("onboard:add_week",
                                           back_section="shift_type"),
        )
        return

    if action == "add_week":
        answer = parts[2] if len(parts) > 2 else "no"

        if answer == "yes":
            ob_data["selected_days"] = []
            update_user(chat_id, onboard_data=json.dumps(ob_data))
            week_num = len(ob_data.get("weeks", [])) + 1
            await query.edit_message_text(
                f"{onboard_progress_text(\'shift_days\')}\\n\\n"
                f"Pick your Week {week_num} days:",
                reply_markup=onboard_days_kb([]),
            )
        else:
            # Done — compile and save
            weeks = ob_data.get("weeks", [])
            if not weeks:
                # Fallback: shouldn't happen but guard
                await query.answer("No days saved. Please pick your days.", show_alert=True)
                return

            # Back-compat: always store week1_days + week2_days for other modules
            ob_data["week1_days"] = weeks[0]
            ob_data["week2_days"] = weeks[1] if len(weeks) > 1 else weeks[0]
            ob_data.pop("selected_days", None)
            update_user(chat_id, onboard_data=json.dumps(ob_data), onboard_step="partners_intro")

            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO shifts (chat_id, shift_type, week1_days, week2_days) "
                    "VALUES (?, ?, ?, ?)",
                    (chat_id, ob_data.get("shift_type", "custom"),
                     json.dumps(ob_data["week1_days"]), json.dumps(ob_data["week2_days"])),
                )

            week_summary = _format_weeks_summary(weeks)
            await query.edit_message_text(
                f"{onboard_progress_text(\'partners_intro\')}\\n\\n"
                f"Schedule saved.\\n{week_summary}\\n\\n"
                "Next up: people and relationships.",
                reply_markup=onboard_section_done_kb("partners_intro",
                                                     back_section="shift_type"),
            )
        return'''

assert OLD_SCHEDULE in src, "OLD_SCHEDULE block not found!"
src = src.replace(OLD_SCHEDULE, NEW_SCHEDULE, 1)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 2: Add _format_weeks_summary helper after _check_duplicate function
# ─────────────────────────────────────────────────────────────────────────────

OLD_HELPER_ANCHOR = '''\
# ─────────────────────────────────────────────────────────────────────────────
# START COMMAND
# ─────────────────────────────────────────────────────────────────────────────'''

NEW_HELPER_INSERT = '''\
# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULE DISPLAY HELPER
# ─────────────────────────────────────────────────────────────────────────────

# Sun-Sat display order and names (Python weekday: Mon=0 … Sun=6)
_DISPLAY_ORDER = [6, 0, 1, 2, 3, 4, 5]  # Sun first
_DAY_ABBR = {6: "Sun", 0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat"}


def _days_to_str(day_list: list[int]) -> str:
    """Convert a list of weekday ints to comma-separated names in Sun-Sat order."""
    day_set = set(day_list)
    return ", ".join(_DAY_ABBR[d] for d in _DISPLAY_ORDER if d in day_set)


def _format_weeks_summary(weeks: list[list[int]]) -> str:
    """Format a list of week day-lists into a readable summary."""
    if not weeks:
        return "(no days saved)"
    lines = []
    for i, week in enumerate(weeks, 1):
        lines.append(f"  Week {i}: {_days_to_str(week)}")
    return "\\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# START COMMAND
# ─────────────────────────────────────────────────────────────────────────────'''

assert OLD_HELPER_ANCHOR in src, "START COMMAND anchor not found!"
src = src.replace(OLD_HELPER_ANCHOR, NEW_HELPER_INSERT, 1)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 3: Partner name handler — after insert, save partner_id and show type picker
# ─────────────────────────────────────────────────────────────────────────────

OLD_PARTNER = '''\
        with db() as conn:
            conn.execute(
                "INSERT INTO partners (chat_id, name) VALUES (?, ?)",
                (chat_id, name),
            )
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"Added {name} 💜\\n\\nAnother person?",
            reply_markup=onboard_yes_no_kb("onboard:another_partner"),
        )
        return True'''

NEW_PARTNER = '''\
        with db() as conn:
            cursor = conn.execute(
                "INSERT INTO partners (chat_id, name) VALUES (?, ?)",
                (chat_id, name),
            )
            partner_id = cursor.lastrowid
        ob_data["pending_partner_id"] = partner_id
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        context.user_data["awaiting"] = None
        # Show relationship type picker before asking "another?"
        type_kb = _onboard_partner_type_kb(partner_id)
        await update.message.reply_text(
            f"Added {name} 💜\\n\\nWhat\\'s their relationship to you?",
            reply_markup=type_kb,
        )
        return True'''

assert OLD_PARTNER in src, "OLD_PARTNER block not found!"
src = src.replace(OLD_PARTNER, NEW_PARTNER, 1)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 4: Add partner_type handler in _dispatch_onboard_action
#          (after another_partner block, before bills_intro)
# ─────────────────────────────────────────────────────────────────────────────

OLD_AFTER_ANOTHER_PARTNER = '''\
    if action == "another_partner":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="partner_name")
            context.user_data["awaiting"] = AWAITING_PARTNER_NAME
            await query.edit_message_text(
                f"{onboard_progress_text(\'partners_intro\')}\\n\\n"
                "Type their name:",
                reply_markup=onboard_skip_kb(),
            )
        else:
            update_user(chat_id, onboard_step="bills_intro")
            await query.edit_message_text(
                f"{onboard_progress_text(\'bills_intro\')}\\n\\n"
                "People saved. Next: bills and money.",
                reply_markup=onboard_section_done_kb("bills_intro",
                                                     back_section="partners"),
            )
        return'''

NEW_AFTER_ANOTHER_PARTNER = '''\
    if action == "partner_type":
        # onboard:partner_type:{type_key}
        type_key = parts[2] if len(parts) > 2 else "important"
        partner_id = ob_data.get("pending_partner_id")
        if partner_id and type_key in RELATIONSHIP_TYPES:
            with db() as conn:
                conn.execute(
                    "UPDATE partners SET relationship_type = ? WHERE id = ? AND chat_id = ?",
                    (type_key, partner_id, chat_id),
                )
        ob_data.pop("pending_partner_id", None)
        update_user(chat_id, onboard_data=json.dumps(ob_data))
        emoji, label = RELATIONSHIP_TYPES.get(type_key, ("💜", "Person"))
        await query.edit_message_text(
            f"{emoji} Got it — saved as {label}.\\n\\nAnother person?",
            reply_markup=onboard_yes_no_kb("onboard:another_partner"),
        )
        return

    if action == "another_partner":
        answer = parts[2] if len(parts) > 2 else "no"
        if answer == "yes":
            update_user(chat_id, onboard_step="partner_name")
            context.user_data["awaiting"] = AWAITING_PARTNER_NAME
            await query.edit_message_text(
                f"{onboard_progress_text(\'partners_intro\')}\\n\\n"
                "Type their name:",
                reply_markup=onboard_skip_kb(),
            )
        else:
            update_user(chat_id, onboard_step="bills_intro")
            await query.edit_message_text(
                f"{onboard_progress_text(\'bills_intro\')}\\n\\n"
                "People saved. Next: bills and money.",
                reply_markup=onboard_section_done_kb("bills_intro",
                                                     back_section="partners"),
            )
        return'''

assert OLD_AFTER_ANOTHER_PARTNER in src, "OLD_AFTER_ANOTHER_PARTNER block not found!"
src = src.replace(OLD_AFTER_ANOTHER_PARTNER, NEW_AFTER_ANOTHER_PARTNER, 1)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 5: Add _onboard_partner_type_kb helper before the START COMMAND section
# ─────────────────────────────────────────────────────────────────────────────

OLD_START_CMD = '''\
# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULE DISPLAY HELPER
# ─────────────────────────────────────────────────────────────────────────────'''

NEW_START_CMD = '''\
# ─────────────────────────────────────────────────────────────────────────────
# ONBOARDING KEYBOARD HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _onboard_partner_type_kb(partner_id: int):
    """Relationship-type picker with onboard:partner_type callback pattern."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for key, (emoji, label) in RELATIONSHIP_TYPES.items():
        rows.append([InlineKeyboardButton(
            f"{emoji} {label}",
            callback_data=f"onboard:partner_type:{key}",
        )])
    return InlineKeyboardMarkup(rows)


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULE DISPLAY HELPER
# ─────────────────────────────────────────────────────────────────────────────'''

assert OLD_START_CMD in src, "SCHEDULE DISPLAY HELPER anchor not found for partner_type_kb insert!"
src = src.replace(OLD_START_CMD, NEW_START_CMD, 1)

# ─────────────────────────────────────────────────────────────────────────────
# WRITE
# ─────────────────────────────────────────────────────────────────────────────

with open("modules/onboarding.py", "w") as f:
    f.write(src)

print("Patch applied successfully.")
