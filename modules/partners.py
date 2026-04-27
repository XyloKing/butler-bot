# Butler Bot
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
💜 People & Dates module.
Partner tracking, birthdays, anniversaries, date scheduling.
Now with relationship types, interaction frequency, and button-based date picker.
"""
import random
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import db
from helpers import today, days_until, friendly_date
from modules.wellness import log_event
from keyboards import (
    partners_list_kb, partner_detail_kb, back_to_menu_kb,
    relationship_type_kb, interaction_freq_kb,
    date_pick_mmdd_month_kb, date_pick_mmdd_day_kb,
    date_pick_month_kb, date_pick_day_kb,
    RELATIONSHIP_TYPES, INTERACTION_FREQUENCIES,
)

AWAITING_PARTNER_NAME = "partner_name"
AWAITING_PARTNER_EMOJI = "partner_emoji"
AWAITING_DATE_VALUE = "partner_date_value"


async def partners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all partners:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    item_id = int(parts[-1]) if len(parts) > 2 and parts[-1].isdigit() else None

    if action == "view":
        await _show_partners_list(query, chat_id)

    elif action == "detail":
        await _show_partner_detail(query, chat_id, item_id)

    elif action == "add":
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✕ Cancel", callback_data="menu:main")]])
        await query.edit_message_text("What's their name?", reply_markup=cancel_kb)
        context.user_data["awaiting"] = AWAITING_PARTNER_NAME

    elif action == "picktype":
        # Show relationship type picker
        pid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else item_id
        await query.edit_message_text(
            "What's your relationship?\n\nThis helps me pick the right emoji and notifications.",
            reply_markup=relationship_type_kb(pid),
        )

    elif action == "settype":
        # partners:settype:{id}:{type_key}
        pid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        type_key = parts[3] if len(parts) > 3 else "partner"
        if pid and type_key in RELATIONSHIP_TYPES:
            emoji, label = RELATIONSHIP_TYPES[type_key]
            with db() as conn:
                conn.execute(
                    "UPDATE partners SET relationship_type = ?, emoji = ? WHERE id = ? AND chat_id = ?",
                    (type_key, emoji, pid, chat_id),
                )
            await query.edit_message_text(
                f"✅ Set to {emoji} {label}",
                reply_markup=partner_detail_kb(pid),
            )

    elif action == "pickfreq":
        # Show interaction frequency picker
        pid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else item_id
        await query.edit_message_text(
            "How often do you want to be reminded to connect with them?",
            reply_markup=interaction_freq_kb(pid),
        )

    elif action == "setfreq":
        # partners:setfreq:{id}:{freq_key}
        pid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        freq_key = parts[3] if len(parts) > 3 else "flexible"
        if pid and freq_key in INTERACTION_FREQUENCIES:
            label = INTERACTION_FREQUENCIES[freq_key]
            with db() as conn:
                conn.execute(
                    "UPDATE partners SET interaction_freq = ? WHERE id = ? AND chat_id = ?",
                    (freq_key, pid, chat_id),
                )
            await query.edit_message_text(
                f"✅ Interaction frequency: {label}",
                reply_markup=partner_detail_kb(pid),
            )

    elif action == "settarget":
        # partners:settarget:{id}:{val}
        pid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        val = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 2
        if pid:
            with db() as conn:
                conn.execute(
                    "UPDATE partners SET target_dates_per_month = ? WHERE id = ? AND chat_id = ?",
                    (val, pid, chat_id),
                )
            await query.edit_message_text(
                f"✅ Target: {val} date{'s' if val != 1 else ''}/month",
                reply_markup=partner_detail_kb(pid),
            )

    elif action == "adddate":
        date_type = parts[2] if len(parts) > 2 else "custom"
        partner_id = int(parts[3]) if len(parts) > 3 else None

        context.user_data["pending_date_type"] = date_type
        context.user_data["pending_date_partner"] = partner_id

        if date_type in ("birthday", "anniversary"):
            # Use MM-DD picker for recurring dates
            prefix = f"pdatepick:{partner_id}:{date_type}"
            if date_type == "birthday":
                msg = "🎂 Pick their birth month:"
            else:
                msg = "💕 Pick the anniversary month:"
            await query.edit_message_text(msg, reply_markup=date_pick_mmdd_month_kb(prefix))
        else:
            # Full date picker for one-off dates
            prefix = f"pdatepick:{partner_id}:{date_type}"
            await query.edit_message_text(
                "📅 Pick the date — choose a month:",
                reply_markup=date_pick_month_kb(prefix),
            )

    elif action == "schedule":
        # Show ALL 7 days this week — user picks any day, work or off
        from helpers import is_working
        with db() as conn:
            partner = conn.execute("SELECT * FROM partners WHERE id = ? AND chat_id = ?",
                                   (item_id, chat_id)).fetchone()

        name = partner["name"] if partner else "them"
        d = today()
        from datetime import timedelta

        # Count dates this week
        from modules.today import _dates_this_week
        dates_this_week = _dates_this_week(chat_id, d)

        # Sunday-first: find start of this week
        start = d - timedelta(days=(d.weekday() + 1) % 7)

        # Show all 7 days — label by work status but allow booking any day
        rows = []
        for i in range(7):
            day = start + timedelta(days=i)
            working = is_working(chat_id, day)
            work_icon = "🏥" if working else "🏠"
            work_label = " (work night)" if working else ""
            label = f"{work_icon} {day.strftime('%a %m/%d')}{work_label}"
            rows.append([InlineKeyboardButton(
                label,
                callback_data=f"partners:booked:{item_id}:{day.isoformat()}"
            )])
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"partners:detail:{item_id}")])

        if dates_this_week >= 2:
            header = f"⚠️ 2 dates already this week. You can still add more — no hard cap."
        elif dates_this_week == 1:
            header = f"📅 1 date logged this week. Pick a day for {name}:"
        else:
            header = f"📅 Pick a day for {name}:\n(Work nights shown — you can still pick those)"

        await query.edit_message_text(
            header,
            reply_markup=InlineKeyboardMarkup(rows),
        )

    elif action == "booked":
        partner_id = int(parts[2]) if len(parts) > 2 else None
        date_str = parts[3] if len(parts) > 3 else None

        # Recovery day social guard
        recovery_warning = ""
        if date_str:
            try:
                from datetime import date as _date
                from helpers import is_working, get_user_shift
                from helpers import get_shift_info
                booked_date = _date.fromisoformat(date_str)
                day_before = booked_date - timedelta(days=1)
                shift = get_user_shift(chat_id)
                if shift and is_working(chat_id, day_before) and not is_working(chat_id, booked_date):
                    # Day after a work shift = recovery day
                    recovery_warning = (
                        "\n\n⚠️ Recovery day — this is the day after your shift. "
                        "Consider planning for 5pm or later."
                    )
            except Exception:
                pass

        with db() as conn:
            partner = conn.execute("SELECT name FROM partners WHERE id = ?", (partner_id,)).fetchone()
            conn.execute(
                "INSERT INTO partner_dates (partner_id, chat_id, date_type, label, date_value, recurring) "
                "VALUES (?, ?, 'date_night', 'Date Night', ?, 0)",
                (partner_id, chat_id, date_str),
            )
        log_event(chat_id, "dates", "logged", ref_id=partner_id)
        name = partner["name"] if partner else "them"
        await query.edit_message_text(
            f"💜 Date with {name} on {date_str} — locked in.\n\nI'll remind you the day before.{recovery_warning}",
            reply_markup=partner_detail_kb(partner_id),
        )

    elif action == "editfield":
        # callback_data = partners:editfield:{id}:{field}
        pid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else item_id
        field = parts[3] if len(parts) > 3 else "name"
        from modules.field_editor import start_field_edit
        await start_field_edit(update, context, "partners", pid, field)

    elif action == "delete":
        from keyboards import confirm_delete_kb
        with db() as conn:
            partner = conn.execute("SELECT name FROM partners WHERE id = ? AND chat_id = ?",
                                   (item_id, chat_id)).fetchone()
        name = partner["name"] if partner else "this person"
        await query.edit_message_text(
            f"⚠️ Remove {name} and ALL their dates/birthdays/anniversaries?\n\n"
            "This cannot be undone.",
            reply_markup=confirm_delete_kb("partners", item_id),
        )

    elif action == "confirm_delete":
        with db() as conn:
            conn.execute("DELETE FROM partner_dates WHERE partner_id = ? AND chat_id = ?", (item_id, chat_id))
            conn.execute("DELETE FROM partners WHERE id = ? AND chat_id = ?", (item_id, chat_id))
        await query.edit_message_text(random.choice(["Gone.", "Removed.", "Deleted."]), reply_markup=back_to_menu_kb())


async def _show_partners_list(query, chat_id):
    partners = _get_partners(chat_id)
    if not partners:
        await query.edit_message_text(
            "No people added yet.\n\nTap below to add someone.",
            reply_markup=partners_list_kb([]),
        )
        return

    text = "💜 PEOPLE & DATES\n\nTap someone for details:"
    await query.edit_message_text(text, reply_markup=partners_list_kb(partners))


async def _show_partner_detail(query, chat_id, partner_id):
    with db() as conn:
        partner = conn.execute("SELECT * FROM partners WHERE id = ? AND chat_id = ?",
                               (partner_id, chat_id)).fetchone()
        dates = conn.execute(
            "SELECT * FROM partner_dates WHERE partner_id = ? AND chat_id = ? ORDER BY date_value",
            (partner_id, chat_id)
        ).fetchall()

    if not partner:
        await query.edit_message_text("Person not found.", reply_markup=back_to_menu_kb())
        return

    # Get relationship-based emoji
    rel_type = dict(partner).get("relationship_type")
    if rel_type and rel_type in RELATIONSHIP_TYPES:
        emoji = RELATIONSHIP_TYPES[rel_type][0]
        type_label = RELATIONSHIP_TYPES[rel_type][1]
    else:
        emoji = partner["emoji"] or "💜"
        type_label = None

    # Get interaction frequency
    freq = dict(partner).get("interaction_freq")
    freq_label = INTERACTION_FREQUENCIES.get(freq, None)

    lines = [
        f"{emoji} {partner['name']}",
    ]
    if type_label:
        lines.append(f"Type: {type_label}")
    if freq_label:
        lines.append(f"Check-in: {freq_label}")
    lines.append(f"Target: ~{partner['target_dates_per_month']} dates/month")
    lines.append("")

    if dates:
        lines.append("Important dates:")
        d = today()
        for pd_row in dates:
            dv = pd_row["date_value"]
            label = pd_row["label"] or pd_row["date_type"]
            if len(dv) == 5:  # MM-DD recurring
                try:
                    this_year = date(d.year, int(dv[:2]), int(dv[3:]))
                    if this_year < d:
                        this_year = date(d.year + 1, int(dv[:2]), int(dv[3:]))
                    lines.append(f"  🔄 {label}: {dv} — {friendly_date(this_year)}")
                except ValueError:
                    lines.append(f"  🔄 {label}: {dv}")
            else:
                try:
                    target = date.fromisoformat(dv)
                    lines.append(f"  📅 {label}: {friendly_date(target)}")
                except ValueError:
                    lines.append(f"  📅 {label}: {dv}")
    else:
        lines.append("No dates added yet.")

    await query.edit_message_text("\n".join(lines), reply_markup=partner_detail_kb(partner_id))


def _get_partners(chat_id) -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM partners WHERE chat_id = ? ORDER BY name", (chat_id,)).fetchall()
    return [dict(r) for r in rows]


async def handle_partner_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for partner operations."""
    awaiting = context.user_data.get("awaiting")
    if not awaiting or not awaiting.startswith("partner"):
        return False

    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if awaiting == AWAITING_PARTNER_NAME:
        # Create partner, then ask for relationship type
        with db() as conn:
            cursor = conn.execute(
                "INSERT INTO partners (chat_id, name) VALUES (?, ?)",
                (chat_id, text),
            )
            partner_id = cursor.lastrowid
        context.user_data["awaiting"] = None
        # Go straight to relationship type picker
        msg = random.choice([
            f"Added {text}. 💜",
            f"{text} is in. 💜",
            f"Got {text}. 💜",
        ])
        await update.message.reply_text(
            f"{msg}\n\nWhat's your relationship?",
            reply_markup=relationship_type_kb(partner_id),
        )
        return True

    if awaiting == AWAITING_DATE_VALUE:
        date_type = context.user_data.pop("pending_date_type", "custom")
        partner_id = context.user_data.pop("pending_date_partner", None)
        context.user_data["awaiting"] = None

        # Normalize date
        date_val = text.strip()
        recurring = 1 if len(date_val) == 5 else 0  # MM-DD = recurring

        with db() as conn:
            conn.execute(
                "INSERT INTO partner_dates (partner_id, chat_id, date_type, date_value, recurring) "
                "VALUES (?, ?, ?, ?, ?)",
                (partner_id, chat_id, date_type, date_val, recurring),
            )

        await update.message.reply_text(
            f"✅ Saved {date_type}: {date_val}",
            reply_markup=partner_detail_kb(partner_id),
        )
        return True

    if awaiting == "partner_edit_name":
        partner_id = context.user_data.pop("edit_partner_id", None)
        context.user_data["awaiting"] = None
        if text.lower() != "skip" and partner_id:
            with db() as conn:
                conn.execute("UPDATE partners SET name = ? WHERE id = ? AND chat_id = ?",
                             (text, partner_id, chat_id))
        partners = _get_partners(chat_id)
        await update.message.reply_text("Updated.", reply_markup=partners_list_kb(partners))
        return True

    return False


async def partner_date_picker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pdatepick:* callbacks for the button-based date picker in partner flows."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    # Format: pdatepick:{partner_id}:{date_type}:{action}:{value}
    parts = data.split(":")
    partner_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    date_type = parts[2] if len(parts) > 2 else "custom"
    action = parts[3] if len(parts) > 3 else ""
    value = parts[4] if len(parts) > 4 else ""
    prefix = f"pdatepick:{partner_id}:{date_type}"

    if action == "cancel":
        await query.edit_message_text("Cancelled.", reply_markup=partner_detail_kb(partner_id))

    elif action == "mmdd_m":
        # Month selected for MM-DD picker — show days
        month = int(value) if value else int(parts[4]) if len(parts) > 4 else 1
        await query.edit_message_text(
            f"📅 Pick the day:",
            reply_markup=date_pick_mmdd_day_kb(prefix, month),
        )

    elif action == "mmdd_d":
        # Day selected for MM-DD picker — save it
        mmdd = value  # e.g. "03-15"
        recurring = 1
        label = date_type.replace("_", " ").title()
        with db() as conn:
            conn.execute(
                "INSERT INTO partner_dates (partner_id, chat_id, date_type, label, date_value, recurring) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (partner_id, chat_id, date_type, label, mmdd, recurring),
            )
        await query.edit_message_text(
            f"✅ Saved {label}: {mmdd}",
            reply_markup=partner_detail_kb(partner_id),
        )

    elif action == "mmdd_back":
        # Back to month picker
        await query.edit_message_text(
            "📅 Pick the month:",
            reply_markup=date_pick_mmdd_month_kb(prefix),
        )

    elif action == "yr":
        # Year changed — show months for that year
        year = int(value) if value else date.today().year
        await query.edit_message_text(
            "📅 Pick a month:",
            reply_markup=date_pick_month_kb(prefix, year),
        )

    elif action == "month":
        # Month selected — show days
        month = int(value) if value else 1
        year_str = parts[5] if len(parts) > 5 else str(date.today().year)
        year = int(year_str)
        await query.edit_message_text(
            "📅 Pick the day:",
            reply_markup=date_pick_day_kb(prefix, month, year),
        )

    elif action == "day":
        # Full date selected — save it
        date_str = value  # e.g. "2026-04-15"
        label = date_type.replace("_", " ").title()
        with db() as conn:
            conn.execute(
                "INSERT INTO partner_dates (partner_id, chat_id, date_type, label, date_value, recurring) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (partner_id, chat_id, date_type, label, date_str),
            )
        await query.edit_message_text(
            f"✅ Saved {label}: {date_str}",
            reply_markup=partner_detail_kb(partner_id),
        )
