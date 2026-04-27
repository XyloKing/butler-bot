# Butler Bot — Me Time Tracker
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""Log and track personal time. Feeds the suggestions engine so it can
detect when you haven't had me-time in X days and flag it."""

from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes

from database import db
from helpers import today, now
from modules.wellness import log_event
from keyboards import (
    metime_log_activity_kb, metime_log_duration_kb, metime_view_kb,
    back_to_menu_kb,
)

ACTIVITY_LABELS = {
    "gaming":    "🎮 Gaming",
    "music":     "🎵 Music",
    "rest":      "🛋️ Rest",
    "outdoors":  "🏕️ Outside",
    "creative":  "🎨 Creative",
    "media":     "📺 Movie/Show",
    "reading":   "📚 Reading",
    "social":    "👫 Social",
    "other":     "✅ Other",
}


async def metime_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle metime:* callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "view"

    if action == "view":
        await _show_metime_view(query, chat_id)

    elif action == "start":
        # Show activity picker
        await query.edit_message_text(
            "🏠 ME TIME\n\nWhat were you up to?",
            reply_markup=metime_log_activity_kb(),
        )

    elif action == "log":
        # Activity selected — show duration picker
        activity = parts[2] if len(parts) > 2 else "other"
        label = ACTIVITY_LABELS.get(activity, activity)
        await query.edit_message_text(
            f"{label} — how long?",
            reply_markup=metime_log_duration_kb(activity),
        )

    elif action == "dur":
        # Duration selected — save the log
        # metime:dur:{activity}:{hours}
        activity = parts[2] if len(parts) > 2 else "other"
        try:
            duration = float(parts[3]) if len(parts) > 3 else 1.0
        except ValueError:
            duration = 1.0

        with db() as conn:
            cursor = conn.execute(
                "INSERT INTO me_time_logs (chat_id, activity, duration_hr) VALUES (?, ?, ?)",
                (chat_id, activity, duration),
            )
            log_id = cursor.lastrowid
        log_event(chat_id, "me_time", "logged", ref_id=log_id)

        label = ACTIVITY_LABELS.get(activity, activity)
        dur_str = f"{int(duration)} hr" if duration >= 1 else "30 min"
        if duration > 1:
            dur_str = f"{int(duration)} hrs"

        await query.edit_message_text(
            f"✅ Logged: {label} — {dur_str}\n\nGood. You need that.",
            reply_markup=metime_view_kb(),
        )

    elif action == "history":
        await _show_history(query, chat_id)


async def _show_metime_view(query, chat_id):
    """Show me-time status and options."""
    d = today()
    last_log = _last_metime(chat_id)
    total_this_week = _hours_this_week(chat_id, d)
    days_since = _days_since_metime(chat_id, d)

    lines = ["🏠 ME TIME\n"]

    if last_log:
        activity = ACTIVITY_LABELS.get(last_log["activity"], last_log["activity"])
        if days_since == 0:
            lines.append(f"Last logged: Today ({activity})")
        elif days_since == 1:
            lines.append(f"Last logged: Yesterday ({activity})")
        else:
            lines.append(f"Last logged: {days_since} days ago ({activity})")
    else:
        lines.append("No me-time logged yet.")

    if total_this_week:
        lines.append(f"This week: {total_this_week:.1f} hrs")

    lines.append("")

    if days_since is None or days_since >= 5:
        lines.append("⚠️ It's been a while. You're overdue.")
    elif days_since >= 3:
        lines.append("Worth making time for yourself soon.")
    else:
        lines.append("You're doing alright.")

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=metime_view_kb(),
    )


async def _show_history(query, chat_id):
    """Show recent me-time logs."""
    with db() as conn:
        logs = conn.execute(
            "SELECT * FROM me_time_logs WHERE chat_id = ? ORDER BY logged_at DESC LIMIT 10",
            (chat_id,),
        ).fetchall()

    if not logs:
        await query.edit_message_text(
            "No me-time logged yet.\n\nTap below to log some.",
            reply_markup=metime_view_kb(),
        )
        return

    lines = ["🏠 ME TIME HISTORY\n"]
    for log in logs:
        activity = ACTIVITY_LABELS.get(log["activity"], log["activity"])
        dur = log["duration_hr"] or 1.0
        dur_str = f"{dur:.0f} hr" if dur == 1 else f"{dur:.1f} hrs"
        # Parse date from logged_at
        try:
            dt_str = log["logged_at"][:10]  # YYYY-MM-DD
            from datetime import date as _date
            logged_date = _date.fromisoformat(dt_str)
            delta = (today() - logged_date).days
            when = "Today" if delta == 0 else f"{delta}d ago"
        except Exception:
            when = ""
        lines.append(f"  {activity} — {dur_str}  ({when})")

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=metime_view_kb(),
    )


# ── Public helpers for suggestions engine ────────────────────────────────

def _last_metime(chat_id: int):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM me_time_logs WHERE chat_id = ? ORDER BY logged_at DESC LIMIT 1",
            (chat_id,),
        ).fetchone()


def _days_since_metime(chat_id: int, d=None) -> int | None:
    """Returns days since last me-time log, or None if never logged."""
    if d is None:
        d = today()
    log = _last_metime(chat_id)
    if not log:
        return None
    try:
        from datetime import date as _date
        logged = _date.fromisoformat(log["logged_at"][:10])
        return (d - logged).days
    except (ValueError, TypeError):
        return None


def _hours_this_week(chat_id: int, d=None) -> float:
    """Total me-time hours this week (Sun–Sat)."""
    if d is None:
        d = today()
    from datetime import timedelta
    start = d - timedelta(days=(d.weekday() + 1) % 7)  # Sunday
    with db() as conn:
        row = conn.execute(
            "SELECT SUM(duration_hr) as total FROM me_time_logs "
            "WHERE chat_id = ? AND date(logged_at) >= ?",
            (chat_id, start.isoformat()),
        ).fetchone()
    return row["total"] or 0.0
