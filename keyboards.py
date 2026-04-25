# Butler Bot
# (c) 2026 D.Escar — github.com/XyloKing/butler-bot

"""
All inline keyboard layouts in one place.
Button-first UX — user should almost never type.

Callback data format: "section:action:id"
Examples: "menu:main", "bills:view", "bills:paid:3", "partner:add"
"""
import calendar
from datetime import date
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ── RELATIONSHIP TYPE EMOJI MAPPING ──

RELATIONSHIP_TYPES = {
    "partner":    ("💜", "Partner"),
    "friend":     ("💚", "Friend"),
    "family":     ("🧡", "Family"),
    "important":  ("⭐", "Important Person"),
}

INTERACTION_FREQUENCIES = {
    "daily":    "Every day",
    "weekly":   "~Once a week",
    "biweekly": "Every 2 weeks",
    "monthly":  "~Once a month",
    "flexible": "No set schedule",
}


# ── BUTTON-BASED DATE PICKER (month → day → year) ──

def date_pick_month_kb(callback_prefix: str, year: int = None) -> InlineKeyboardMarkup:
    """Step 1: Pick a month. callback_prefix identifies the flow (e.g. 'datepick:appts:3')."""
    if year is None:
        year = date.today().year
    months = [
        ("Jan", 1), ("Feb", 2), ("Mar", 3), ("Apr", 4),
        ("May", 5), ("Jun", 6), ("Jul", 7), ("Aug", 8),
        ("Sep", 9), ("Oct", 10), ("Nov", 11), ("Dec", 12),
    ]
    rows = []
    for i in range(0, 12, 3):
        row = []
        for name, num in months[i:i+3]:
            row.append(InlineKeyboardButton(
                name, callback_data=f"{callback_prefix}:month:{num}:{year}"
            ))
        rows.append(row)
    # Year toggle
    rows.append([
        InlineKeyboardButton(f"◀ {year - 1}", callback_data=f"{callback_prefix}:yr:{year - 1}"),
        InlineKeyboardButton(f"📅 {year}", callback_data="noop"),
        InlineKeyboardButton(f"{year + 1} ▶", callback_data=f"{callback_prefix}:yr:{year + 1}"),
    ])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=f"{callback_prefix}:cancel")])
    return InlineKeyboardMarkup(rows)


def date_pick_day_kb(callback_prefix: str, month: int, year: int) -> InlineKeyboardMarkup:
    """Step 2: Pick a day for the selected month/year."""
    month_name = calendar.month_abbr[month]
    days_in_month = calendar.monthrange(year, month)[1]
    rows = []
    # Header
    rows.append([InlineKeyboardButton(f"📅 {month_name} {year}", callback_data="noop")])
    # Day grid — 7 per row
    row = []
    for d in range(1, days_in_month + 1):
        row.append(InlineKeyboardButton(
            str(d), callback_data=f"{callback_prefix}:day:{year}-{month:02d}-{d:02d}"
        ))
        if len(row) == 7:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back to months", callback_data=f"{callback_prefix}:yr:{year}")])
    return InlineKeyboardMarkup(rows)


def date_pick_mmdd_month_kb(callback_prefix: str) -> InlineKeyboardMarkup:
    """Step 1 for MM-DD only picker (recurring dates like birthdays)."""
    months = [
        ("Jan", 1), ("Feb", 2), ("Mar", 3), ("Apr", 4),
        ("May", 5), ("Jun", 6), ("Jul", 7), ("Aug", 8),
        ("Sep", 9), ("Oct", 10), ("Nov", 11), ("Dec", 12),
    ]
    rows = []
    for i in range(0, 12, 3):
        row = []
        for name, num in months[i:i+3]:
            row.append(InlineKeyboardButton(
                name, callback_data=f"{callback_prefix}:mmdd_m:{num}"
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=f"{callback_prefix}:cancel")])
    return InlineKeyboardMarkup(rows)


def date_pick_mmdd_day_kb(callback_prefix: str, month: int) -> InlineKeyboardMarkup:
    """Step 2 for MM-DD picker — pick a day."""
    month_name = calendar.month_abbr[month]
    # Use a leap year to get max days
    days_in_month = calendar.monthrange(2000, month)[1]
    rows = []
    rows.append([InlineKeyboardButton(f"📅 {month_name}", callback_data="noop")])
    row = []
    for d in range(1, days_in_month + 1):
        row.append(InlineKeyboardButton(
            str(d), callback_data=f"{callback_prefix}:mmdd_d:{month:02d}-{d:02d}"
        ))
        if len(row) == 7:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back to months", callback_data=f"{callback_prefix}:mmdd_back")])
    return InlineKeyboardMarkup(rows)


# ── MAIN MENU ──

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Today / Tonight",  callback_data="today:view")],
        [InlineKeyboardButton("📆 Week View",        callback_data="week:view")],
        [
            InlineKeyboardButton("💸 Money & Bills",  callback_data="bills:view"),
            InlineKeyboardButton("💜 People & Dates", callback_data="partners:view"),
        ],
        [
            InlineKeyboardButton("🚗 Car / Admin",    callback_data="car:view"),
            InlineKeyboardButton("🎓 Credentials",    callback_data="creds:view"),
        ],
        [
            InlineKeyboardButton("💊 Meds",           callback_data="meds:view"),
            InlineKeyboardButton("📒 Notes",          callback_data="notes:view"),
        ],
        [InlineKeyboardButton("📅 Appointments",     callback_data="appts:view")],
        [InlineKeyboardButton("➕ Capture / Inbox",   callback_data="capture:start")],
        [InlineKeyboardButton("⚙️ Settings",         callback_data="settings:view")],
    ])


# ── BACK BUTTON (always available) ──

def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu:main")],
    ])


def back_button_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")]


# ── TODAY / TONIGHT ──

def metime_log_activity_kb() -> InlineKeyboardMarkup:
    """Pick what you did for me-time."""
    activities = [
        ("🎮 Gaming",      "gaming"),
        ("🎵 Music",       "music"),
        ("🛋️ Rest",        "rest"),
        ("🏕️ Outside",    "outdoors"),
        ("🎨 Creative",    "creative"),
        ("📺 Movie/Show",  "media"),
        ("📚 Reading",     "reading"),
        ("👫 Social",      "social"),
        ("✅ Other",        "other"),
    ]
    rows = []
    row = []
    for label, val in activities:
        row.append(InlineKeyboardButton(label, callback_data=f"metime:log:{val}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="today:metime")])
    return InlineKeyboardMarkup(rows)


def metime_log_duration_kb(activity: str) -> InlineKeyboardMarkup:
    """Pick how long you spent."""
    durations = [("30 min", 0.5), ("1 hr", 1), ("2 hrs", 2), ("3 hrs", 3), ("4+ hrs", 4)]
    rows = [[InlineKeyboardButton(label, callback_data=f"metime:dur:{activity}:{val}") for label, val in durations]]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="metime:start")])
    return InlineKeyboardMarkup(rows)


def metime_view_kb() -> InlineKeyboardMarkup:
    """Me-time main view buttons."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Log Me Time",    callback_data="metime:start")],
        [InlineKeyboardButton("📊 History",       callback_data="metime:history")],
        [InlineKeyboardButton("⬅️ Back",          callback_data="today:view")],
    ])


def today_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💊 Log Meds Taken", callback_data="meds:taken"),
            InlineKeyboardButton("📒 Add Note",       callback_data="notes:add:today"),
        ],
        [
            InlineKeyboardButton("📅 Alter Schedule", callback_data="alter:start"),
            InlineKeyboardButton("🔄 Refresh",        callback_data="today:view"),
        ],
        [
            InlineKeyboardButton("🏠 Me Time",    callback_data="today:metime"),
            InlineKeyboardButton("💡 Suggestions", callback_data="today:suggest"),
        ],
        [InlineKeyboardButton("📊 Quick Analyze", callback_data="today:analyze")],
        back_button_row(),
    ])


# ── BILLS / MONEY ──

def bills_list_kb(bills: list[dict]) -> InlineKeyboardMarkup:
    """Show each bill as a button. Paid ones are struck-through."""
    rows = []
    for b in bills:
        paid = "✅ " if b["paid_this_cycle"] else "⬜ "
        amt = f" ${b['amount']:,.0f}" if b["amount"] else ""
        label = f"{paid}{b['name']}{amt}"
        rows.append([InlineKeyboardButton(label, callback_data=f"bills:detail:{b['id']}")])

    rows.append([
        InlineKeyboardButton("➕ Add Bill", callback_data="bills:add"),
        InlineKeyboardButton("💰 Payday Summary", callback_data="bills:payday"),
    ])
    rows.append(back_button_row())
    return InlineKeyboardMarkup(rows)


def bill_detail_kb(bill_id: int, is_paid: bool) -> InlineKeyboardMarkup:
    rows = []
    if not is_paid:
        rows.append([InlineKeyboardButton("✅ Mark PAID", callback_data=f"bills:paid:{bill_id}")])
    else:
        rows.append([InlineKeyboardButton("↩️ Mark Unpaid", callback_data=f"bills:unpaid:{bill_id}")])
    rows.append([
        InlineKeyboardButton("📝 Name", callback_data=f"bills:editfield:{bill_id}:name"),
        InlineKeyboardButton("💰 Amount", callback_data=f"bills:editfield:{bill_id}:amount"),
    ])
    rows.append([
        InlineKeyboardButton("📅 Due Day", callback_data=f"bills:editfield:{bill_id}:due_day"),
        InlineKeyboardButton("🔄 Frequency", callback_data=f"bills:editfield:{bill_id}:frequency"),
    ])
    rows.append([
        InlineKeyboardButton("👤 Account/User", callback_data=f"bills:editfield:{bill_id}:account_user"),
        InlineKeyboardButton("📒 Note", callback_data=f"notes:add:bill:{bill_id}"),
    ])
    rows.append([
        InlineKeyboardButton("🗑 Delete", callback_data=f"bills:delete:{bill_id}"),
    ])
    rows.append([InlineKeyboardButton("⬅️ Bills", callback_data="bills:view")])
    return InlineKeyboardMarkup(rows)


# ── PARTNERS / DATES ──

def partners_list_kb(partners: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for p in partners:
        # Use relationship-based emoji if available, fall back to custom emoji
        try:
            rel_type = p.get("relationship_type") or p["relationship_type"]
        except (KeyError, TypeError):
            rel_type = None
        if rel_type and rel_type in RELATIONSHIP_TYPES:
            emoji = RELATIONSHIP_TYPES[rel_type][0]
        else:
            emoji = p.get("emoji") or "💜"
        rows.append([InlineKeyboardButton(
            f"{emoji} {p['name']}",
            callback_data=f"partners:detail:{p['id']}"
        )])
    rows.append([InlineKeyboardButton("➕ Add Person", callback_data="partners:add")])
    rows.append(back_button_row())
    return InlineKeyboardMarkup(rows)


def partner_detail_kb(partner_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎂 Add Birthday",    callback_data=f"partners:adddate:birthday:{partner_id}"),
            InlineKeyboardButton("💕 Add Anniversary",  callback_data=f"partners:adddate:anniversary:{partner_id}"),
        ],
        [
            InlineKeyboardButton("📅 Schedule Date",    callback_data=f"partners:schedule:{partner_id}"),
            InlineKeyboardButton("📒 Add Note",         callback_data=f"notes:add:partner:{partner_id}"),
        ],
        [
            InlineKeyboardButton("📝 Name",  callback_data=f"partners:editfield:{partner_id}:name"),
            InlineKeyboardButton("👥 Type",  callback_data=f"partners:picktype:{partner_id}"),
        ],
        [
            InlineKeyboardButton("🔔 Frequency", callback_data=f"partners:pickfreq:{partner_id}"),
            InlineKeyboardButton("🎯 Dates/Month", callback_data=f"partners:editfield:{partner_id}:target_dates_per_month"),
        ],
        [
            InlineKeyboardButton("🗑 Remove",       callback_data=f"partners:delete:{partner_id}"),
        ],
        [InlineKeyboardButton("⬅️ People", callback_data="partners:view")],
    ])


def relationship_type_kb(partner_id: int) -> InlineKeyboardMarkup:
    """Pick a relationship type for a person."""
    rows = []
    for key, (emoji, label) in RELATIONSHIP_TYPES.items():
        rows.append([InlineKeyboardButton(
            f"{emoji} {label}",
            callback_data=f"partners:settype:{partner_id}:{key}"
        )])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"partners:detail:{partner_id}")])
    return InlineKeyboardMarkup(rows)


def interaction_freq_kb(partner_id: int) -> InlineKeyboardMarkup:
    """Pick how often you want to interact with this person."""
    rows = []
    for key, label in INTERACTION_FREQUENCIES.items():
        rows.append([InlineKeyboardButton(
            label, callback_data=f"partners:setfreq:{partner_id}:{key}"
        )])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"partners:detail:{partner_id}")])
    return InlineKeyboardMarkup(rows)


# ── CAR / ADMIN ──

def car_list_kb(events: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for e in events:
        done = "✅ " if e["done"] else ""
        from helpers import days_until, urgency_emoji
        d = __import__("datetime").date.fromisoformat(e["due_date"])
        urg = urgency_emoji(days_until(d))
        rows.append([InlineKeyboardButton(
            f"{done}{urg} {e['description']}",
            callback_data=f"car:detail:{e['id']}"
        )])
    rows.append([InlineKeyboardButton("➕ Add Item", callback_data="car:add")])
    rows.append(back_button_row())
    return InlineKeyboardMarkup(rows)


def car_detail_kb(event_id: int, is_done: bool) -> InlineKeyboardMarkup:
    rows = []
    if not is_done:
        rows.append([InlineKeyboardButton("✅ Mark Done", callback_data=f"car:done:{event_id}")])
    else:
        rows.append([InlineKeyboardButton("↩️ Reopen", callback_data=f"car:undone:{event_id}")])
    rows.append([
        InlineKeyboardButton("📝 Description", callback_data=f"car:editfield:{event_id}:description"),
        InlineKeyboardButton("📅 Due Date",    callback_data=f"car:editfield:{event_id}:due_date"),
    ])
    rows.append([
        InlineKeyboardButton("💨 Mileage",     callback_data=f"car:editfield:{event_id}:mileage"),
        InlineKeyboardButton("📒 Note",         callback_data=f"notes:add:car:{event_id}"),
    ])
    rows.append([
        InlineKeyboardButton("🗑 Delete", callback_data=f"car:delete:{event_id}"),
    ])
    rows.append([InlineKeyboardButton("⬅️ Car/Admin", callback_data="car:view")])
    return InlineKeyboardMarkup(rows)


# ── CREDENTIALS ──

def creds_list_kb(creds: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for c in creds:
        from helpers import days_until, urgency_emoji
        try:
            d = __import__("datetime").date.fromisoformat(c["expiry_date"])
            urg = urgency_emoji(days_until(d))
        except (ValueError, TypeError):
            urg = "⚠️"
        rows.append([InlineKeyboardButton(
            f"{urg} {c['name']} — exp {c['expiry_date'] or 'unknown'}",
            callback_data=f"creds:detail:{c['id']}"
        )])
    rows.append([InlineKeyboardButton("➕ Add Credential", callback_data="creds:add")])
    rows.append(back_button_row())
    return InlineKeyboardMarkup(rows)


def cred_detail_kb(cred_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Mark Renewed", callback_data=f"creds:renewed:{cred_id}")],
        [
            InlineKeyboardButton("📝 Name",      callback_data=f"creds:editfield:{cred_id}:name"),
            InlineKeyboardButton("🔢 License #",  callback_data=f"creds:editfield:{cred_id}:credential_num"),
        ],
        [
            InlineKeyboardButton("📍 State",      callback_data=f"creds:editfield:{cred_id}:state"),
            InlineKeyboardButton("📅 Expiry",     callback_data=f"creds:editfield:{cred_id}:expiry_date"),
        ],
        [
            InlineKeyboardButton("🔄 Renews every", callback_data=f"creds:setrenewal:{cred_id}:_pick"),
            InlineKeyboardButton("📚 CEUs",        callback_data=f"creds:setceu:{cred_id}:_pick"),
        ],
        [
            InlineKeyboardButton("🎯 CEU Req'd",   callback_data=f"creds:editfield:{cred_id}:ceu_required"),
            InlineKeyboardButton("✅ CEU Done",    callback_data=f"creds:editfield:{cred_id}:ceu_completed"),
        ],
        [
            InlineKeyboardButton("🏢 Issuer",     callback_data=f"creds:editfield:{cred_id}:issuing_body"),
            InlineKeyboardButton("🔗 Renewal URL", callback_data=f"creds:editfield:{cred_id}:renewal_url"),
        ],
        [
            InlineKeyboardButton("📒 Note", callback_data=f"notes:add:cred:{cred_id}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"creds:delete:{cred_id}"),
        ],
        [InlineKeyboardButton("⬅️ Credentials", callback_data="creds:view")],
    ])


# ── MEDICATIONS ──

def med_schedule_kb(med_id: int) -> InlineKeyboardMarkup:
    """When should this med be taken?"""
    options = [
        ("🌅 Morning",           f"meds:setschedule:{med_id}:morning"),
        ("☀️ Midday",             f"meds:setschedule:{med_id}:midday"),
        ("🌆 Evening",           f"meds:setschedule:{med_id}:evening"),
        ("🌙 Bedtime",           f"meds:setschedule:{med_id}:bedtime"),
        ("⏰ As needed (PRN)",    f"meds:setschedule:{med_id}:prn"),
        ("⏭ Skip for now",         f"meds:detail:{med_id}"),
    ]
    return InlineKeyboardMarkup([[InlineKeyboardButton(l, callback_data=c)] for l, c in options])


def med_frequency_kb(med_id: int) -> InlineKeyboardMarkup:
    """How often is this med taken?"""
    options = [
        ("Every day",              f"meds:setfreq:{med_id}:daily"),
        ("Twice a day",            f"meds:setfreq:{med_id}:twice_daily"),
        ("Every other day",        f"meds:setfreq:{med_id}:every_other"),
        ("Weekly",                 f"meds:setfreq:{med_id}:weekly"),
        ("As needed (PRN)",        f"meds:setfreq:{med_id}:prn"),
        ("⏭ Skip for now",         f"meds:detail:{med_id}"),
    ]
    return InlineKeyboardMarkup([[InlineKeyboardButton(l, callback_data=c)] for l, c in options])


def cred_renewal_freq_kb(cred_id: int) -> InlineKeyboardMarkup:
    """How often does this credential need to be renewed?"""
    options = [
        ("Every year",             f"creds:setrenewal:{cred_id}:1yr"),
        ("Every 2 years",          f"creds:setrenewal:{cred_id}:2yr"),
        ("Every 3 years",          f"creds:setrenewal:{cred_id}:3yr"),
        ("Every 5 years",          f"creds:setrenewal:{cred_id}:5yr"),
        ("Varies / doesn't expire",f"creds:setrenewal:{cred_id}:varies"),
        ("⏭ Skip for now",         f"creds:detail:{cred_id}"),
    ]
    return InlineKeyboardMarkup([[InlineKeyboardButton(l, callback_data=c)] for l, c in options])


def cred_ceu_kb(cred_id: int) -> InlineKeyboardMarkup:
    """Does this credential require continuing education units?"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Yes, requires CEUs",    callback_data=f"creds:setceu:{cred_id}:yes")],
        [InlineKeyboardButton("No CEUs required",      callback_data=f"creds:setceu:{cred_id}:no")],
        [InlineKeyboardButton("⏭ Skip",                callback_data=f"creds:detail:{cred_id}")],
    ])


def touch_frequency_kb(current: int = 2) -> InlineKeyboardMarkup:
    """How often should Maurice check in per day?"""
    options = [
        (1, "Once a day"),
        (2, "Twice a day"),
        (3, "3x a day"),
        (4, "4x a day"),
        (6, "6x a day"),
        (8, "8x a day"),
        (0, "Never (I'll open it myself)"),
    ]
    rows = []
    for val, label in options:
        check = " ✓" if val == current else ""
        rows.append([InlineKeyboardButton(f"{label}{check}", callback_data=f"settings:settouches:{val}")])
    rows.append([InlineKeyboardButton("⬅️ Settings", callback_data="settings:view")])
    return InlineKeyboardMarkup(rows)


def onboard_payday_kb() -> InlineKeyboardMarkup:
    """Payday schedule picker for onboarding."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Every Friday (weekly)",    callback_data="onboard:payday:weekly_friday")],
        [InlineKeyboardButton("Every other Friday",       callback_data="onboard:payday:biweekly_friday")],
        [InlineKeyboardButton("1st and 15th of month",   callback_data="onboard:payday:first_fifteenth")],
        [InlineKeyboardButton("Once a month",            callback_data="onboard:payday:monthly")],
        [InlineKeyboardButton("I’m not sure / skip",     callback_data="onboard:payday:skip")],
    ])


def meds_list_kb(meds: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for m in meds:
        taken = "✅ " if m["taken_today"] else "⬜ "
        rows.append([InlineKeyboardButton(
            f"{taken}{m['name']} {m['dosage'] or ''}".strip(),
            callback_data=f"meds:detail:{m['id']}"
        )])
    rows.append([
        InlineKeyboardButton("💊 All Taken", callback_data="meds:all_taken"),
        InlineKeyboardButton("➕ Add Med",   callback_data="meds:add"),
    ])
    rows.append(back_button_row())
    return InlineKeyboardMarkup(rows)


def med_detail_kb(med_id: int, taken: bool) -> InlineKeyboardMarkup:
    rows = []
    if not taken:
        rows.append([InlineKeyboardButton("✅ Taken", callback_data=f"meds:take:{med_id}")])
    else:
        rows.append([InlineKeyboardButton("↩️ Undo", callback_data=f"meds:untake:{med_id}")])
    rows.append([
        InlineKeyboardButton("📝 Name",    callback_data=f"meds:editfield:{med_id}:name"),
        InlineKeyboardButton("💊 Dosage",   callback_data=f"meds:editfield:{med_id}:dosage"),
    ])
    rows.append([
        InlineKeyboardButton("🌅 Schedule",  callback_data=f"meds:setschedule:{med_id}:_pick"),
        InlineKeyboardButton("🔄 Frequency", callback_data=f"meds:setfreq:{med_id}:_pick"),
    ])
    rows.append([
        InlineKeyboardButton("📅 Refill",    callback_data=f"meds:editfield:{med_id}:refill_date"),
    ])
    rows.append([
        InlineKeyboardButton("📒 Note",  callback_data=f"notes:add:med:{med_id}"),
        InlineKeyboardButton("🗑 Remove", callback_data=f"meds:delete:{med_id}"),
    ])
    rows.append([InlineKeyboardButton("⬅️ Meds", callback_data="meds:view")])
    return InlineKeyboardMarkup(rows)


# ── NOTES ──

def notes_list_kb(notes: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for n in notes:
        preview = (n["content"][:30] + "…") if len(n["content"]) > 30 else n["content"]
        cat = dict(n).get("category") or ""
        rows.append([InlineKeyboardButton(
            f"📒 {cat}: {preview}" if cat else f"📒 {preview}",
            callback_data=f"notes:detail:{n['id']}"
        )])
    rows.append([InlineKeyboardButton("📒 New Note", callback_data="notes:add:general")])
    rows.append(back_button_row())
    return InlineKeyboardMarkup(rows)


# ── APPOINTMENTS ──

def appts_list_kb(appts: list[dict]) -> InlineKeyboardMarkup:
    """Show each appointment as a button with category emoji + priority indicator."""
    rows = []
    from helpers import days_until, urgency_emoji
    from modules.appointments import CATEGORY_EMOJI, PRIORITY_LABELS
    import datetime as _dt

    for a in appts:
        done = "✅ " if a["done"] else ""
        d = _dt.date.fromisoformat(a["event_date"])
        urg = urgency_emoji(days_until(d))
        # Get category emoji (safe for old rows without column)
        cat = a.get("category") or "other"
        cat_emoji = CATEGORY_EMOJI.get(cat, "📋")
        # Get priority indicator
        prio = dict(a).get("priority")
        prio = prio if prio is not None else 2
        prio_short = {0: "🔕", 1: "🔔", 2: "🔔🔔", 3: "🔔🔔🔔", 4: "🚨"}.get(prio, "")

        label = f"{done}{cat_emoji}{prio_short} {a['title']} — {a['event_date']}"
        # Telegram limits callback data to 64 bytes, label is just display
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"appts:detail:{a['id']}")])

    rows.append([InlineKeyboardButton("➕ Add Appointment", callback_data="appts:add")])
    rows.append(back_button_row())
    return InlineKeyboardMarkup(rows)


def appt_detail_kb(appt_id: int, is_done: bool) -> InlineKeyboardMarkup:
    rows = []
    if not is_done:
        rows.append([InlineKeyboardButton("✅ Mark Done", callback_data=f"appts:done:{appt_id}")])
    else:
        rows.append([InlineKeyboardButton("↩️ Reopen", callback_data=f"appts:undone:{appt_id}")])
    rows.append([
        InlineKeyboardButton("📝 Title", callback_data=f"appts:editfield:{appt_id}:title"),
        InlineKeyboardButton("📅 Date",  callback_data=f"appts:editfield:{appt_id}:event_date"),
    ])
    rows.append([
        InlineKeyboardButton("⏰ Time",  callback_data=f"appts:editfield:{appt_id}:event_time"),
        InlineKeyboardButton("📒 Notes", callback_data=f"appts:editfield:{appt_id}:notes"),
    ])
    rows.append([
        InlineKeyboardButton("📂 Category", callback_data=f"appts:editcategory:{appt_id}"),
        InlineKeyboardButton("⚡ Priority", callback_data=f"appts:editpriority:{appt_id}"),
    ])
    rows.append([
        InlineKeyboardButton("🗑 Delete", callback_data=f"appts:delete:{appt_id}"),
    ])
    rows.append([InlineKeyboardButton("⬅️ Appointments", callback_data="appts:view")])
    return InlineKeyboardMarkup(rows)


# ── CAPTURE / INBOX ──

def capture_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 New Bill",          callback_data="bills:add")],
        [InlineKeyboardButton("🚗 New Car Item",      callback_data="car:add")],
        [InlineKeyboardButton("💜 New Partner",        callback_data="partners:add")],
        [InlineKeyboardButton("🎓 New Credential",    callback_data="creds:add")],
        [InlineKeyboardButton("💊 New Medication",     callback_data="meds:add")],
        [InlineKeyboardButton("📅 New Appointment",    callback_data="appts:add")],
        [InlineKeyboardButton("📒 Quick Note",         callback_data="notes:add:general")],
        back_button_row(),
    ])


# ── CONFIRMATION DIALOGS ──

def confirm_delete_kb(category: str, item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑 Yes, Delete", callback_data=f"{category}:confirm_delete:{item_id}"),
            InlineKeyboardButton("❌ Cancel",      callback_data=f"{category}:view"),
        ],
    ])


# ── FOLLOW-UP ("Did you do the thing?") ──

def followup_kb(category: str, item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"{category}:done:{item_id}"),
            InlineKeyboardButton("❌ No",  callback_data=f"{category}:skip:{item_id}"),
        ],
        [InlineKeyboardButton("⏰ Remind Later", callback_data=f"{category}:snooze:{item_id}")],
    ])


# ── ONBOARDING ──

# Progress steps for onboarding sections (1-based display)
# Map of section name → (step_number, label)
ONBOARD_PROGRESS = {
    "name":          (1, "Your Name"),
    "shift_type":    (2, "Work Schedule"),
    "shift_days":    (2, "Work Schedule"),
    "partners_intro":(3, "People"),
    "bills_intro":   (4, "Bills"),
    "car_intro":     (5, "Car & Admin"),
    "creds_intro":   (6, "Credentials"),
    "meds_intro":    (7, "Meds"),
}
ONBOARD_TOTAL_STEPS = 7


def onboard_progress_text(section: str) -> str:
    """Return a progress indicator line for the given onboarding section."""
    step, label = ONBOARD_PROGRESS.get(section, (1, "Setup"))
    return f"📊 Step {step} of {ONBOARD_TOTAL_STEPS} — {label}"


def onboard_welcome_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Let's Set Up", callback_data="onboard:start")],
        [InlineKeyboardButton("⏭ Skip for Now",  callback_data="onboard:skip")],
    ])


def onboard_shift_type_kb() -> InlineKeyboardMarkup:
    """Shift type picker with back button."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌙 Nights (7p-7a)",  callback_data="onboard:shift:7p-7a")],
        [InlineKeyboardButton("☀️ Days (7a-7p)",   callback_data="onboard:shift:7a-7p")],
        [InlineKeyboardButton("🔄 Rotating",         callback_data="onboard:shift:rotating")],
        [InlineKeyboardButton("✏️ Custom",            callback_data="onboard:shift:custom")],
        [InlineKeyboardButton("⬅️ Back",              callback_data="onboard:back:name")],
    ])


# Day order: Sunday first (Sun=6, Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5)
_SUN_SAT_ORDER = [6, 0, 1, 2, 3, 4, 5]
_DAY_NAMES = {6: "Sun", 0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat"}


def onboard_days_kb(selected: list[int] = None, week_label: str = "") -> InlineKeyboardMarkup:
    """Single-row weekday picker (Sun-Sat). 7 buttons in one line."""
    selected = selected or []
    _ORDER = [6, 0, 1, 2, 3, 4, 5]  # Sun first
    _SHORT = {6: "Su", 0: "Mo", 1: "Tu", 2: "We", 3: "Th", 4: "Fr", 5: "Sa"}
    row = []
    for day_num in _ORDER:
        check = "✅" if day_num in selected else "⬜"
        row.append(InlineKeyboardButton(f"{check}{_SHORT[day_num]}", callback_data=f"onboard:day:{day_num}"))
    rows = [row]
    rows.append([InlineKeyboardButton("✔️ Done", callback_data="onboard:days_done")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="onboard:back:shift_type")])
    return InlineKeyboardMarkup(rows)


def schedule_14day_grid_kb(w1_days: list[int], w2_days: list[int]) -> InlineKeyboardMarkup:
    """14-button grid showing Sun-Sat × 2 weeks for the rotating schedule."""
    rows = []
    # Header row
    header = [InlineKeyboardButton(d, callback_data="noop") for d in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]]
    rows.append(header)
    # Week 1 row
    w1_row = []
    for day_num in _SUN_SAT_ORDER:
        if day_num in w1_days:
            w1_row.append(InlineKeyboardButton("🏥", callback_data="noop"))
        else:
            w1_row.append(InlineKeyboardButton("🏠", callback_data="noop"))
    rows.append(w1_row)
    # Week 2 row
    w2_row = []
    for day_num in _SUN_SAT_ORDER:
        if day_num in w2_days:
            w2_row.append(InlineKeyboardButton("🏥", callback_data="noop"))
        else:
            w2_row.append(InlineKeyboardButton("🏠", callback_data="noop"))
    rows.append(w2_row)
    return InlineKeyboardMarkup(rows)


def onboard_section_done_kb(next_section: str, back_section: str = None) -> InlineKeyboardMarkup:
    """Next/Skip/Back buttons for between-section screens."""
    rows = [
        [InlineKeyboardButton("➡️ Next", callback_data=f"onboard:{next_section}")],
        [InlineKeyboardButton("⏭ Skip Rest", callback_data="onboard:finish")],
    ]
    if back_section:
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"onboard:back:{back_section}")])
    return InlineKeyboardMarkup(rows)


def onboard_yes_no_kb(callback_prefix: str, back_section: str = None) -> InlineKeyboardMarkup:
    """Yes/No keyboard with optional back button."""
    rows = [
        [
            InlineKeyboardButton("👍 Yes", callback_data=f"{callback_prefix}:yes"),
            InlineKeyboardButton("👎 No",  callback_data=f"{callback_prefix}:no"),
        ],
    ]
    if back_section:
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"onboard:back:{back_section}")])
    return InlineKeyboardMarkup(rows)


def onboard_car_type_kb() -> InlineKeyboardMarkup:
    """Car item type picker for onboarding."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛢 Oil Change",    callback_data="onboard:car_type:oil_change")],
        [InlineKeyboardButton("🔍 Inspection",    callback_data="onboard:car_type:inspection")],
        [InlineKeyboardButton("📋 Registration",  callback_data="onboard:car_type:registration")],
        [InlineKeyboardButton("🛱 Insurance",     callback_data="onboard:car_type:insurance")],
        [InlineKeyboardButton("🔧 Tire / Brake",  callback_data="onboard:car_type:tire_brake")],
        [InlineKeyboardButton("✏️ Custom item",  callback_data="onboard:car_type:custom")],
        [InlineKeyboardButton("⏭ Skip",            callback_data="onboard:skip_item")],
    ])


def onboard_bill_frequency_kb() -> InlineKeyboardMarkup:
    """Bill frequency picker for onboarding."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Every month",       callback_data="onboard:bill_freq:monthly")],
        [InlineKeyboardButton("Every 2 weeks",     callback_data="onboard:bill_freq:biweekly")],
        [InlineKeyboardButton("Every week",        callback_data="onboard:bill_freq:weekly")],
        [InlineKeyboardButton("Once a year",       callback_data="onboard:bill_freq:yearly")],
        [InlineKeyboardButton("One-time / varies", callback_data="onboard:bill_freq:once")],
    ])


def onboard_skip_kb() -> InlineKeyboardMarkup:
    """Skip button shown below text prompts so users have a way out."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Skip", callback_data="onboard:skip_item")],
    ])


# ── SETTINGS ──

def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Notification Times", callback_data="settings:notify")],
        [InlineKeyboardButton("🏥 Work Schedule",      callback_data="settings:schedule")],
        [InlineKeyboardButton("📅 Override Shift Day",  callback_data="settings:override")],
        [InlineKeyboardButton("💰 Payday Settings",    callback_data="settings:payday")],
        [InlineKeyboardButton("🛠 Feature Toggles",    callback_data="settings:toggles")],
        [InlineKeyboardButton("💬 Check-in Frequency",  callback_data="settings:touches")],
        [InlineKeyboardButton("🔄 Re-run Onboarding",  callback_data="onboard:start")],
        back_button_row(),
    ])


def payday_picker_kb() -> InlineKeyboardMarkup:
    """Pick payday schedule type."""
    options = [
        ("💰 Every Friday (weekly)", "weekly_friday"),
        ("💰 Every Other Friday", "biweekly_friday"),
        ("💰 1st & 15th of month", "first_fifteenth"),
        ("💰 Custom day of month", "custom"),
    ]
    rows = [[InlineKeyboardButton(label, callback_data=f"settings:setpayday:{val}")] for label, val in options]
    rows.append([InlineKeyboardButton("⬅️ Settings", callback_data="settings:view")])
    return InlineKeyboardMarkup(rows)


def feature_toggles_kb(toggles: dict) -> InlineKeyboardMarkup:
    """Settings panel showing on/off toggles for each bot feature."""
    features = [
        ("morning_heartbeat", "🌅 Morning Heartbeat"),
        ("med_reminders",    "💊 Med Reminders"),
        ("bill_reminders",   "💸 Bill Reminders"),
        ("appt_reminders",   "📅 Appt Reminders"),
        ("afternoon_digest", "☀️ Afternoon Digest"),
        ("evening_checkin",  "🌙 Evening Check-in"),
        ("weekly_digest",    "📆 Weekly Summary"),
        ("wellness_checks",  "💧 Wellness Checks"),
        ("partner_nudges",   "💜 Partner Nudges"),
    ]
    rows = []
    for key, label in features:
        is_on = toggles.get(key, True)  # default ON
        status = "✅" if is_on else "❌"
        rows.append([InlineKeyboardButton(
            f"{status} {label}",
            callback_data=f"settings:toggle:{key}"
        )])
    rows.append([InlineKeyboardButton("⬅️ Settings", callback_data="settings:view")])
    return InlineKeyboardMarkup(rows)


def schedule_edit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏰ Change Shift Hours", callback_data="settings:edit_shift_type")],
        [InlineKeyboardButton("📅 Change Week 1 Days", callback_data="settings:edit_w1")],
        [InlineKeyboardButton("📅 Change Week 2 Days", callback_data="settings:edit_w2")],
        [InlineKeyboardButton("⬅️ Settings", callback_data="settings:view")],
    ])


def override_day_kb() -> InlineKeyboardMarkup:
    """Quick override: mark today/tomorrow as work or off."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏥 Working Today",    callback_data="settings:override_on:0")],
        [InlineKeyboardButton("🏠 Off Today",        callback_data="settings:override_off:0")],
        [InlineKeyboardButton("🏥 Working Tomorrow", callback_data="settings:override_on:1")],
        [InlineKeyboardButton("🏠 Off Tomorrow",     callback_data="settings:override_off:1")],
        [InlineKeyboardButton("⬅️ Settings", callback_data="settings:view")],
    ])


def alter_schedule_kb(d: date = None) -> InlineKeyboardMarkup:
    """Alter schedule — pick any day this week or use quick toggles."""
    from datetime import timedelta
    if d is None:
        d = date.today()
    start = d - timedelta(days=(d.weekday() + 1) % 7)  # Sunday
    rows = []
    row = []
    for i in range(7):
        day = start + timedelta(days=i)
        label = day.strftime("%a %d")
        row.append(InlineKeyboardButton(label, callback_data=f"alter:day:{day.isoformat()}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("📅 Edit Full Rotation", callback_data="settings:schedule")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="today:view")])
    return InlineKeyboardMarkup(rows)


# ── APPOINTMENT TIME PICKER ──

def time_picker_kb() -> InlineKeyboardMarkup:
    """Button grid of common appointment times."""
    times = [
        ("8am", "08:00"), ("10am", "10:00"), ("12pm", "12:00"), ("2pm", "14:00"),
        ("4pm", "16:00"), ("6pm", "18:00"), ("8pm", "20:00"), ("10pm", "22:00"),
    ]
    rows = []
    row = []
    for label, val in times:
        row.append(InlineKeyboardButton(label, callback_data=f"appts:settime:{val}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⏭ No Time / All Day", callback_data="appts:skip_time")])
    rows.append([InlineKeyboardButton("✏️ Type Custom Time", callback_data="appts:type_time")])
    return InlineKeyboardMarkup(rows)


# ── MEDICATION FREQUENCY PICKER ──

def frequency_picker_kb(module: str, item_id: int) -> InlineKeyboardMarkup:
    """Button picker for medication frequency."""
    options = [
        ("Daily", "daily"),
        ("Twice daily", "twice_daily"),
        ("Weekly", "weekly"),
        ("As needed", "as_needed"),
    ]
    rows = [[InlineKeyboardButton(label, callback_data=f"{module}:setfreq:{item_id}:{val}")] for label, val in options]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"{module}:detail:{item_id}")])
    return InlineKeyboardMarkup(rows)


# ── BILL FREQUENCY PICKER ──

def bill_frequency_picker_kb(item_id: int) -> InlineKeyboardMarkup:
    """Button picker for bill payment frequency."""
    options = [
        ("Monthly", "monthly"),
        ("Biweekly", "biweekly"),
        ("Weekly", "weekly"),
        ("Once", "once"),
    ]
    rows = [[InlineKeyboardButton(label, callback_data=f"bills:setfreq:{item_id}:{val}")] for label, val in options]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"bills:detail:{item_id}")])
    return InlineKeyboardMarkup(rows)


# ── TARGET DATES PER MONTH PICKER ──

def target_dates_picker_kb(item_id: int) -> InlineKeyboardMarkup:
    """Button picker for target dates per month."""
    options = [("1", 1), ("2", 2), ("3", 3), ("4+", 4)]
    rows = [[InlineKeyboardButton(label, callback_data=f"partners:settarget:{item_id}:{val}")] for label, val in options]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"partners:detail:{item_id}")])
    return InlineKeyboardMarkup(rows)


# ── DUE DAY PICKER (1-31 grid) ──

def due_day_picker_kb() -> InlineKeyboardMarkup:
    """Button grid for picking a due day of month (1-31)."""
    rows = []
    row = []
    for d in range(1, 32):
        row.append(InlineKeyboardButton(str(d), callback_data=f"bills:setdueday:{d}"))
        if len(row) == 7:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⏭ Skip", callback_data="bills:skipdueday")])
    return InlineKeyboardMarkup(rows)


# ── SETTINGS SHIFT TYPE PICKER ──

def settings_shift_type_kb() -> InlineKeyboardMarkup:
    """Shift type picker for Settings (updates existing record)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌙 Nights (7p-7a)",  callback_data="settings:set_shift_type:7p-7a")],
        [InlineKeyboardButton("☀️ Days (7a-7p)",   callback_data="settings:set_shift_type:7a-7p")],
        [InlineKeyboardButton("🔄 Rotating",         callback_data="settings:set_shift_type:rotating")],
        [InlineKeyboardButton("✏️ Custom",            callback_data="settings:set_shift_type:custom")],
        [InlineKeyboardButton("⬅️ Back",              callback_data="settings:schedule")],
    ])
