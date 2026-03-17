"""
All inline keyboard layouts in one place.
Button-first UX — user should almost never type.

Callback data format: "section:action:id"
Examples: "menu:main", "bills:view", "bills:paid:3", "partner:add"
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ═══════════════════════════════════════════════════════
# MAIN MENU
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# BACK BUTTON (always available)
# ═══════════════════════════════════════════════════════

def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu:main")],
    ])


def back_button_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")]


# ═══════════════════════════════════════════════════════
# TODAY / TONIGHT
# ═══════════════════════════════════════════════════════

def today_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💊 Log Meds Taken", callback_data="meds:taken"),
            InlineKeyboardButton("📒 Add Note",       callback_data="notes:add:today"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh",        callback_data="today:view"),
        ],
        back_button_row(),
    ])


# ═══════════════════════════════════════════════════════
# BILLS / MONEY
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# PARTNERS / DATES
# ═══════════════════════════════════════════════════════

def partners_list_kb(partners: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for p in partners:
        try:
            emoji = p["emoji"] or "💜"
        except (IndexError, KeyError):
            emoji = "💜"
        rows.append([InlineKeyboardButton(
            f"{emoji} {p['name']}",
            callback_data=f"partners:detail:{p['id']}"
        )])
    rows.append([InlineKeyboardButton("➕ Add Partner", callback_data="partners:add")])
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
            InlineKeyboardButton("😀 Emoji", callback_data=f"partners:editfield:{partner_id}:emoji"),
        ],
        [
            InlineKeyboardButton("🎯 Dates/Month", callback_data=f"partners:editfield:{partner_id}:target_dates_per_month"),
            InlineKeyboardButton("🗑 Remove",       callback_data=f"partners:delete:{partner_id}"),
        ],
        [InlineKeyboardButton("⬅️ People", callback_data="partners:view")],
    ])


# ═══════════════════════════════════════════════════════
# CAR / ADMIN
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# CREDENTIALS
# ═══════════════════════════════════════════════════════

def creds_list_kb(creds: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for c in creds:
        from helpers import days_until, urgency_emoji
        d = __import__("datetime").date.fromisoformat(c["expiry_date"])
        urg = urgency_emoji(days_until(d))
        rows.append([InlineKeyboardButton(
            f"{urg} {c['name']} — exp {c['expiry_date']}",
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


# ═══════════════════════════════════════════════════════
# MEDICATIONS
# ═══════════════════════════════════════════════════════

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
        InlineKeyboardButton("🔄 Frequency", callback_data=f"meds:editfield:{med_id}:frequency"),
        InlineKeyboardButton("📅 Refill",    callback_data=f"meds:editfield:{med_id}:refill_date"),
    ])
    rows.append([
        InlineKeyboardButton("📒 Note",  callback_data=f"notes:add:med:{med_id}"),
        InlineKeyboardButton("🗑 Remove", callback_data=f"meds:delete:{med_id}"),
    ])
    rows.append([InlineKeyboardButton("⬅️ Meds", callback_data="meds:view")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════
# NOTES
# ═══════════════════════════════════════════════════════

def notes_list_kb(notes: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for n in notes:
        preview = (n["content"][:30] + "…") if len(n["content"]) > 30 else n["content"]
        try:
            cat = n["category"] or ""
        except (IndexError, KeyError):
            cat = ""
        rows.append([InlineKeyboardButton(
            f"📒 {cat}: {preview}" if cat else f"📒 {preview}",
            callback_data=f"notes:detail:{n['id']}"
        )])
    rows.append([InlineKeyboardButton("📒 New Note", callback_data="notes:add:general")])
    rows.append(back_button_row())
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════
# APPOINTMENTS
# ═══════════════════════════════════════════════════════

def appts_list_kb(appts: list[dict]) -> InlineKeyboardMarkup:
    """Show each appointment as a button."""
    rows = []
    from helpers import days_until, urgency_emoji
    import datetime as _dt
    for a in appts:
        done = "✅ " if a["done"] else ""
        d = _dt.date.fromisoformat(a["event_date"])
        urg = urgency_emoji(days_until(d))
        time_str = f" {a['event_time']}" if a.get("event_time") else ""
        label = f"{done}{urg} {a['title']} — {a['event_date']}{time_str}"
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
        InlineKeyboardButton("🗑 Delete", callback_data=f"appts:delete:{appt_id}"),
    ])
    rows.append([InlineKeyboardButton("⬅️ Appointments", callback_data="appts:view")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════
# CAPTURE / INBOX
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# CONFIRMATION DIALOGS
# ═══════════════════════════════════════════════════════

def confirm_delete_kb(category: str, item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑 Yes, Delete", callback_data=f"{category}:confirm_delete:{item_id}"),
            InlineKeyboardButton("❌ Cancel",      callback_data=f"{category}:view"),
        ],
    ])


# ═══════════════════════════════════════════════════════
# FOLLOW-UP ("Did you do the thing?")
# ═══════════════════════════════════════════════════════

def followup_kb(category: str, item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"{category}:done:{item_id}"),
            InlineKeyboardButton("❌ No",  callback_data=f"{category}:skip:{item_id}"),
        ],
        [InlineKeyboardButton("⏰ Remind Later", callback_data=f"{category}:snooze:{item_id}")],
    ])


# ═══════════════════════════════════════════════════════
# ONBOARDING
# ═══════════════════════════════════════════════════════

def onboard_welcome_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Let's Set Up", callback_data="onboard:start")],
        [InlineKeyboardButton("⏭ Skip for Now",  callback_data="onboard:skip")],
    ])


def onboard_shift_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌙 Nights (7p-7a)", callback_data="onboard:shift:7p-7a")],
        [InlineKeyboardButton("🌙 Nights (12p-12a)", callback_data="onboard:shift:12p-12a")],
        [InlineKeyboardButton("☀️ Days (7a-7p)", callback_data="onboard:shift:7a-7p")],
        [InlineKeyboardButton("🔄 Rotating", callback_data="onboard:shift:rotating")],
        [InlineKeyboardButton("✏️ Custom", callback_data="onboard:shift:custom")],
    ])


def onboard_days_kb(selected: list[int] = None) -> InlineKeyboardMarkup:
    """Multi-select weekday picker."""
    selected = selected or []
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    row1 = []
    row2 = []
    for i, name in enumerate(days):
        check = "✅ " if i in selected else ""
        btn = InlineKeyboardButton(f"{check}{name}", callback_data=f"onboard:day:{i}")
        if i < 4:
            row1.append(btn)
        else:
            row2.append(btn)
    return InlineKeyboardMarkup([
        row1, row2,
        [InlineKeyboardButton("✔️ Done", callback_data="onboard:days_done")],
    ])


def onboard_section_done_kb(next_section: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Next", callback_data=f"onboard:{next_section}")],
        [InlineKeyboardButton("⏭ Skip Rest", callback_data="onboard:finish")],
    ])


def onboard_yes_no_kb(callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👍 Yes", callback_data=f"{callback_prefix}:yes"),
            InlineKeyboardButton("👎 No",  callback_data=f"{callback_prefix}:no"),
        ],
    ])


# ═══════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════

def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Notification Times", callback_data="settings:notify")],
        [InlineKeyboardButton("🏥 Work Schedule",      callback_data="settings:schedule")],
        [InlineKeyboardButton("📅 Override Shift Day",  callback_data="settings:override")],
        [InlineKeyboardButton("💰 Payday Settings",    callback_data="settings:payday")],
        [InlineKeyboardButton("🔄 Re-run Onboarding",  callback_data="onboard:start")],
        back_button_row(),
    ])


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
