# Butler Bot — Full Gap Analysis
*Audited April 1, 2026. Every module read line-by-line. Brutally honest.*

---

## TODAY / TONIGHT VIEW (`modules/today.py`)

### What was requested:
- Shift-aware greeting that knows 7p-7a schedule
- Show what matters today: meds, bills, car, credentials, partner dates, appointments
- "Alter schedule" button accessible from here
- Quality-of-life suggestions in check-ins
- No social stuff before 5pm on post-shift recovery days (not just a display rule — should be an active warning)
- Context-sensitive summary based on whether working tonight or recovering

### What's built and working:
- Shift-aware greeting (greets based on hour, shows shift status) using `get_shift_info()` which correctly handles 7p-7a
- Meds untaken warning displayed
- Bills due within 3 days displayed with urgency emoji
- Car items due within 30 days displayed
- Credentials expiring within 60 days displayed
- Partner dates within 14 days displayed with relationship-type emoji
- Appointments within 7 days shown with category emoji and time
- Today's notes (last 3) shown
- "Alter Schedule" button in `today_actions_kb()` → routes to `alter:start`
- "Log Meds Taken" shortcut button
- "Add Note" shortcut button
- Refresh button works

### What's MISSING (not implemented at all):
- **No social-before-5pm guard**: The spec says no social stuff before 5pm on post-shift recovery days. There is zero code checking appointment category="social" against recovery-day + time-before-5pm and flagging it.
- **No date budget display**: User wants max 2 dates/week. Today view never shows "You have X dates this week" or "Date budget used."
- **Behavioral intelligence suggestions not surfaced in Today view**: `get_suggestions()` is called in `scheduler.py`'s `_send_digest()` but NOT in `today_view()` itself. Opening the Today view manually never shows suggestions.
- **Post-shift recovery detection in Today view is passive**: `get_shift_info()` returns the string "😴 Post-shift recovery" but Today view doesn't change its behavior based on this — it still shows everything equally. No "protect your sleep window" type header when it's a recovery day.
- **No contextual first-action prompt** (behavioral spec Feature 2): blank state just says "Nothing urgent. Enjoy your day."

### What's BROKEN (implemented but doesn't work correctly):
- `_greeting()` at line 155-160: uses hour 0-5 = "Late night", 6-11 = "Good morning", etc. For a nocturnal user waking at 5pm, "Good morning" fires from 6am-11am (when they're asleep) and "Good evening" fires 5pm-8pm. Not adapted to actual schedule. The shift type is known but ignored in greeting logic.
- `_bill_due_delta()` at line 168: `due.replace(month=due.month + 1)` crashes when `due.month == 12` (December), only `else` branch handles December but the `if` branch has no guard. Actually looking more carefully, only the outer `if bill["due_day"]` branch is affected and month+1 overflow could raise `ValueError`.

### What needs typed input but should use buttons:
- Nothing in Today view itself requires typed input — this module is display-only. ✅

---

## WEEK VIEW (`modules/week_view.py`)

### What was requested:
- 7-day calendar, Sunday-first
- Shows shift days with 🏥/🏠 markers
- Shows bills, appointments, car events, partner dates, credentials
- Prev/next week navigation
- "Alter Schedule" button accessible from here
- Multi-week rotation support (which week am I in?)

### What's built and working:
- ASCII calendar Sunday-first layout via `ascii_week_calendar()`
- Shift days calculated using rotation logic (week1/week2 based on anchor date)
- Bills with `due_day` shown on correct day
- Payday shown every Friday (hardcoded to weekday 4)
- Car events shown on due date
- Partner dates resolved (MM-DD recurring and ISO one-off)
- Credentials expiry shown
- Appointments shown with category emoji and time
- Prev/Next week navigation with `week:prev:{offset}` / `week:next:{offset}`
- "Alter Schedule" button in nav row
- "This Week" snap-back button when on offset view

### What's MISSING (not implemented at all):
- **"Which week am I in?" indicator**: The user has a 2-week rotation. The week view shows work days correctly (derived from rotation math) but never tells the user "You are in Week 1" or "Week 2." This is especially confusing since the rotation is the core of their schedule.
- **Date budget indicator**: No display of "2 dates scheduled this week" or "date budget full" in week view.
- **Post-shift recovery day flagging**: Recovery days (day after a shift) are not marked in the week view. User asked for "no social stuff before 5pm on post-shift recovery days" — the week view never marks which days are recovery days.
- **Override overrides not reflected in week view**: `shift_overrides` table exists and `check_override()` exists in helpers, but `_show_week()` at line 43-46 calls `is_work_day()` directly, bypassing `check_override()`. So manual overrides do NOT appear in the week view.

### What's BROKEN (implemented but doesn't work correctly):
- **Override bypass (critical)**: `week_view.py` line 44-46 calls `is_work_day(check, shift["anchor"], shift["w1"], shift["w2"])` which does NOT check `shift_overrides`. The correct function is `is_working(chat_id, check)` in `helpers.py` which calls `check_override()` first. This means overriding "Working Today" from the Today view or Settings will show correctly in Today view but NOT in Week view.
- **Partner date emoji in week view uses `p.get("emoji")` not relationship_type**: `week_view.py` line 85: `emoji = pd_row.get("emoji") or "💜"` — this ignores `relationship_type` and always uses the custom emoji. The `today.py` module has a `_partner_emoji()` helper that checks `relationship_type` first; week view doesn't use it. Family members could show 💜 instead of 🧡.
- **Payday is hardcoded to Friday**: Line 67 checks `check.weekday() == 4` regardless of user's `payday_weekday` preference stored in `users.payday_weekday`.

### What needs typed input but should use buttons:
- Nothing in week view requires typed input. ✅

---

## BILLS / MONEY (`modules/bills.py`)

### What was requested:
- Track bills with name, amount, due day, frequency
- Mark paid / unpaid
- Payday summary
- Inline edit and delete for every field
- Button-based UX — no typing for basic operations
- Nag until paid on payday

### What's built and working:
- Bills list with paid/unpaid status and amount display
- Tap bill → detail view
- Mark PAID / Mark Unpaid buttons
- Delete with confirmation dialog
- Inline edit for: name, amount, due_day, frequency, account_user (all via `field_editor`)
- Note attachment via `notes:add:bill:{id}`
- Payday summary showing all unpaid with total
- Scheduler nags on payday (Fridays) every 3 hours
- Monthly cycle reset (bills reset to unpaid on the 1st)

### What's MISSING (not implemented at all):
- **"Add Bill" requires typing**: `bills:add` sets `awaiting = AWAITING_BILL_NAME` and asks for typed bill name. There is no button-based bill creation — the entire add flow is typed (name → amount → due day). No quick-add buttons for common bills.
- **Autopay toggle**: `bills.autopay` column exists in the schema but there is no UI to set or display it. The field is completely unreachable.
- **"Due date" (specific date) editing**: The `bills` table has both `due_day` (day of month) and `due_date` (specific ISO date). The edit buttons only expose `due_day`. The `due_date` field is set during creation but cannot be edited via any button.
- **Frequency editing via buttons**: The `frequency` field is editable via `field_editor` but it requires the user to type the value ("monthly / biweekly / weekly / once"). No button picker for frequency.
- **Bill cycle reset is global, not per-user**: `daily_reset()` in `scheduler.py` line 44: `conn.execute("UPDATE bills SET paid_this_cycle = 0")` — no `WHERE chat_id` filter. If there are multiple users, ALL users' bills get reset on the 1st regardless of their billing cycle.

### What's BROKEN (implemented but doesn't work correctly):
- **Bill add flow: "skip" for due day works but amount "skip" loses name**: In `handle_bill_text()`, if user types "skip" for amount (line 192), the code does `context.user_data.pop("new_bill_name", "Bill")` — this is fine. But if they skip amount AND then the bot restarts between steps, `new_bill_name` was only in `context.user_data` (not persisted to DB), so it gets lost. Bills module does NOT persist pending creation data to DB the way `car.py` and `creds.py` do.
- **`_bill_due_delta()` December overflow**: In `today.py` line 168: `due.replace(month=due.month + 1)` will raise `ValueError` in December. This affects Today view and digest. The `else` branch correctly handles December but only fires for `due < d`, not for the month rollover case when `due.month == 12`.
- **Detail view after edit shows wrong paid status**: In `field_editor._send_detail_view()` for bills (line 153-166), it calls `bill_detail_kb(item_id, False)` — hardcoded `False` for paid status instead of reading actual `bill["paid_this_cycle"]`. Actually looking again at line 153: `with db() as conn: bill = conn.execute(...)` — the paid status IS read from the bill row and passed to `bill_detail_kb`. This is actually correct.

### What needs typed input but should use buttons:
- **Bill name entry**: Entirely typed. Should have quick-add buttons for "Rent / Mortgage", "Electric", "Phone", "Internet", "Insurance", "Car Payment", "+ Custom"
- **Bill amount**: Typed. Could use a number pad keyboard or at minimum pre-set amounts
- **Due day**: Typed number 1-31. Should be a calendar/button row of days
- **Frequency**: Typed string. Should be buttons (Monthly / Biweekly / Weekly / Once)

---

## PARTNERS / DATES (`modules/partners.py`)

### What was requested:
- Partner types: partner/friend/family/important person with distinct icons
- Interaction frequency per person
- Target dates per month
- Button-based date picker for birthdays/anniversaries/dates
- Schedule date flow that checks available (non-work) days
- Back-to-back dates OK since capped at 2/week
- No social before 5pm on recovery days (protection)
- Gathering behavioral data on how users answer (not just what they answer)

### What's built and working:
- Relationship types: partner(💜), friend(💚), family(🧡), important(⭐) with button picker
- Interaction frequency picker (daily/weekly/biweekly/monthly/flexible) — button-based
- Target dates per month field (editable via field_editor but typed)
- Birthday/anniversary date picker is fully button-based (MM-DD picker) ✅
- One-off date picker fully button-based ✅
- "Schedule Date" shows free days this week as buttons
- Delete with confirmation
- Add partner requires typing name only (then shows type picker) — minimal typing
- Inline edit for name (via field_editor — typed) and type/freq (via buttons) ✅
- Notes attachment
- Recovery from bot restarts (name goes to DB via relationship_type_kb callback)

### What's MISSING (not implemented at all):
- **2 dates/week cap enforcement**: No code anywhere checks "how many dates are scheduled this week" and warns or blocks when at 2. The database and logic completely ignore this requirement.
- **No social before 5pm on recovery days**: When scheduling a date via `partners:schedule`, the free day picker shows ALL non-work days including recovery days, with no time-of-day restriction. Zero code checks if it's a recovery day and whether the time slot is after 5pm.
- **Date budget display**: Neither the partner detail view nor the list shows "X of 2 dates used this week."
- **"Schedule Date" only shows 7 days**: `partners:schedule` looks at `today()` to `today() + 6 days` only. The user might want to schedule further out.
- **No deduplication of dates**: You can add the same birthday or anniversary multiple times with no warning.
- **Behavioral data gathering**: The spec says "we should be gathering data on how they answer" — there is no interaction logging table, no response_time tracking, no skip pattern analysis. Zero behavioral intelligence features (Features 11-20 from spec) are implemented.
- **Partner nudge via scheduler**: `suggestions.py` has `_partner_nudge()` but it only appears in the digest. There's no proactive push notification nudge for overdue partner interactions.
- **`target_dates_per_month` edit is typed**: Tapping "🎯 Dates/Month" routes to `field_editor` which prompts "Target dates per month? (number)" — requires typing.

### What's BROKEN (implemented but doesn't work correctly):
- **`partners:schedule` ignores overrides**: Like week view, `partners.py` line 140 calls `is_work_day(check, anchor, w1, w2)` directly, bypassing `check_override()`. Overridden days show as work days when scheduling.
- **`partners:schedule` caps at 5 free days**: Line 148: `for fd in free_days[:5]` — silently truncates to 5 days even if there are more free days in the 7-day window.
- **`item_id` extraction logic is fragile**: Line 35: `item_id = int(parts[-1]) if len(parts) > 2 and parts[-1].isdigit() else None` — uses `parts[-1]` (last part). For `partners:settype:{id}:{key}`, parts[-1] is the type key (e.g., "partner"), not the ID, so `item_id` would be `None`. The code compensates by re-extracting `pid = int(parts[2])` in the settype/setfreq handlers, but this inconsistency could cause silent failures in edge cases.
- **Booked date always labeled "Date Night"**: `partners:booked` at line 172 hardcodes `date_type='date_night', label='Date Night'`. There's no option to label it differently when quick-scheduling from the "Schedule Date" flow.

### What needs typed input but should use buttons:
- **Partner name**: Only typed field — this is acceptable as names can't reasonably be button-based.
- **`target_dates_per_month`**: Typed via field_editor. Should be a button row (1 / 2 / 3 / 4+).

---

## CAR / ADMIN (`modules/car.py`)

### What was requested:
- Track oil changes, inspections, registration, tires, custom items
- Due dates, mileage tracking
- Inline edit and delete
- Button-based date picker for due dates
- Countdown alerts in Today view and digests

### What's built and working:
- Car event types selectable via buttons (Oil Change, Inspection, Registration, Tire/Brake, Custom)
- Date picker fully button-based after type selection ✅
- Custom item type requires typed description only (reasonable)
- Mark Done / Reopen
- Inline edit: description, due_date (button date picker), mileage (typed)
- Delete with confirmation
- Pending creation data persisted to DB (survives bot restarts) ✅
- Urgency emoji on list items
- Shows in Today view (30-day window) and digests

### What's MISSING (not implemented at all):
- **Mileage entry has no button option**: When editing mileage via field_editor, user must type. A number-pad style keyboard doesn't exist.
- **No "completed" car items history view**: All done items disappear from practical view. There's no "Show completed" toggle to see past maintenance history.
- **No recurring item support**: Oil changes should recur every 3-6 months. Once marked done, there's no "add next occurrence" button. User must manually re-add.
- **No mileage-based reminders**: The `mileage` field exists but there's no logic to remind based on mileage intervals (e.g., "every 5,000 miles").
- **No notification toggle**: `settings.py` feature toggles don't include a car-reminder toggle. Med reminders, bill reminders, appt reminders are toggleable but car events are not.

### What's BROKEN (implemented but doesn't work correctly):
- **`car:done` action at line 42**: After marking done, it calls `await query.edit_message_text(f"✅ {desc} — done.")` followed immediately by `await _show_car_list(query, chat_id, send_new=True)`. The first edit_message_text succeeds, then `send_new=True` sends a new message. The original message has already been edited. This is messy but functional.
- **`car:addtype` for non-custom types**: Line 80-94 — description is set correctly, but `context.user_data["new_car_type"]` is set at line 67 and then read at line 180. However, `_clear_input_state()` in `bot.py` clears `new_car_type` on ANY button press. But the date picker callback (`cardp:*`) is handled by `car_datepick_callback` which reads from DB (line 218-221), not from `context.user_data`. So this is actually safe. ✅
- **`creds_list_kb` in `keyboards.py` line 337**: Calls `days_until()` which could fail if `c["expiry_date"]` is None or malformed. There's no guard.

### What needs typed input but should use buttons:
- **Custom description**: Only text input in add flow. Acceptable for custom items.
- **Mileage**: Typed number. Could have button shortcuts (5,000 / 10,000 / skip) for common mileage tracking.

---

## CREDENTIALS (`modules/credentials.py`)

### What was requested:
- Track license name, number, state, expiry, issuer, CEU requirements
- Inline edit and delete for all fields
- Button-based date picker for expiry
- Alerts before expiry
- Renewal URL storage

### What's built and working:
- Credential name typed (step 1)
- Expiry date via button date picker ✅
- Detail view with full info display
- Inline edit for: name, credential_num, state, expiry_date (date picker), ceu_required, ceu_completed, issuing_body, renewal_url — all via field_editor
- Mark Renewed button
- Delete with confirmation
- Pending creation data persisted to DB (survives restarts) ✅
- Shows in Today view (60-day window) and digests (60-day window) and weekly digest (90-day window)

### What's MISSING (not implemented at all):
- **CEU edit is typed**: Editing `ceu_required` and `ceu_completed` prompts "How many CEUs required?" — user must type a number. Should be increment/decrement buttons or a number picker.
- **State picker should be buttons**: Editing `state` asks "State? (e.g. PA, NJ)" — typed. For a healthcare worker, the common states could be button shortcuts.
- **Renewal URL is fully typed**: No deep-link or paste assistance.
- **No CEU progress bar or visual**: Detail view shows "CEUs: X/Y" as plain text. No visual progress indicator.
- **No reminder toggle for credentials**: Feature toggles don't include a credential expiry toggle specifically.

### What's BROKEN (implemented but doesn't work correctly):
- **`creds_list_kb` crash risk**: `keyboards.py` line 337: `date.fromisoformat(c["expiry_date"])` — if any credential has a NULL or malformed expiry_date, this crashes the entire credentials list view. No try/except guard. Credentials added with the old flow (before button date picker) could have NULL expiry dates.
- **`handle_cred_text()` calls `_parse_date_loosely` from onboarding**: Line 171-172: `from modules.onboarding import _parse_date_loosely; text = _parse_date_loosely(text)`. But `onboarding._parse_date_loosely` returns a tuple `(ok, iso_str, error)` in the new version (see onboarding.py), while `appointments._parse_date_loosely` returns just a string. Looking at onboarding.py, the function is actually named `parse_date_loosely` (no underscore), returning a tuple. `credentials.py` imports `_parse_date_loosely` (with underscore) — this import would fail if called. However, this branch (`AWAITING_CRED_EDIT_VALUE` with `field == "expiry_date"`) is only reached if user somehow ends up in that state; since expiry edits now route to the date picker via `field_editor`, this code path is mostly dead. Still technically broken.

### What needs typed input but should use buttons:
- **Credential name**: Typed — acceptable, licenses have unique names.
- **License number**: Typed — acceptable, alphanumeric license numbers.
- **State**: Should be button row of 2-letter state codes.
- **CEU counts**: Should be +/- buttons or number picker.
- **Issuing body**: Typed — for healthcare, could have common options (AHA, AARC, NBRC, State Board, etc.).

---

## MEDICATIONS (`modules/meds.py`)

### What was requested:
- Track medication name, dosage, frequency, refill date
- Daily "taken" toggle per medication
- "All taken" bulk button
- Inline edit and delete
- Aggressive nag if not taken
- Refill date reminders

### What's built and working:
- Meds list with ✅/⬜ taken status
- Tap med → detail view
- Taken / Undo taken per individual med
- "All Taken" bulk button ✅
- "Log Meds Taken" shortcut from Today view
- Inline edit: name, dosage, frequency, refill_date — all via field_editor
- Delete with confirmation
- Notes attachment
- Daily reset at midnight
- Med nag every 2 hours during notification window (5am-5pm) if untaken

### What's MISSING (not implemented at all):
- **Frequency field has no button picker**: Editing frequency via field_editor requires typing "daily / weekly / as needed". No button options.
- **Refill date has no date picker via field_editor**: `field_editor` routes `refill_date` to the button date picker (it's in `DATE_FIELDS`) ✅ — this is fine actually.
- **Refill date reminder**: There is NO code anywhere that checks `refill_date` and sends a reminder. `scheduler.py` has `med_nag` for untaken meds but nothing for upcoming refill dates. The field is tracked but never acted upon.
- **"Add Med" flow is entirely typed**: Name prompt → type → dosage prompt → type. No button shortcuts for common med names or dosages.
- **Frequency-based smart reminders**: If frequency is "weekly" or "as needed", the daily nag doesn't respect this — it would nag every day regardless of frequency setting.
- **No "taken at" timestamp**: `taken_today` is a boolean flag, not a timestamp. No history of when medications were taken.

### What's BROKEN (implemented but doesn't work correctly):
- **`meds:taken` in `meds_callback()` line 34-44**: The handler for action `"taken"` AND `"all_taken"` both execute `UPDATE medications SET taken_today = 1 WHERE chat_id = ?` (all meds). The `"taken"` action (from Today view "Log Meds Taken" button) marks ALL meds taken — this is probably intentional per the button label, but it means tapping "Log Meds Taken" from Today view has the same effect as "All Taken" from the meds screen. Not a bug per se but conflates individual and bulk.
- **`handle_med_text()` for `AWAITING_MED_EDIT`**: Lines 170-187 — this state `"med_edit"` is defined as a constant but is never SET anywhere in `meds_callback()`. The `meds:editfield` action goes to `field_editor.start_field_edit()` which sets `"field_edit"` state, not `"med_edit"`. So the `AWAITING_MED_EDIT` branch in `handle_med_text()` is dead code that can never be triggered.
- **Med nag sends the `meds_list_kb` with untaken meds only**: `scheduler.py` line 209: `reply_markup=meds_list_kb([dict(m) for m in untaken])`. If user taps a med from the nag message and marks it taken, then the full med list shows only the untaken subset, not all meds. The display is misleading.

### What needs typed input but should use buttons:
- **Med name**: Typed. Common healthcare worker meds could have shortcuts.
- **Dosage**: Typed. Common dosages (5mg, 10mg, 20mg, 25mg, 50mg, 100mg, skip) could be buttons.
- **Frequency**: Typed. Should be buttons (Daily / Twice daily / Weekly / As needed).

---

## NOTES (`modules/notes.py`)

### What was requested:
- Quick-capture notes attachable to any entity
- General notes and category-specific notes
- View, delete notes

### What's built and working:
- Add note from any entity via `notes:add:{category}:{ref_id}` pattern
- General notes from main menu
- Notes list view with 30-item limit, preview
- Note detail view with delete
- Notes show on Today view (last 3 today's notes)
- Capture/Inbox includes "Quick Note" shortcut
- Notes attached to bills, car, partners, creds, meds all work

### What's MISSING (not implemented at all):
- **No note editing**: Notes can be created and deleted but not edited. There's no `notes:edit:{id}` or `notes:editfield:{id}:content` path.
- **No note search**: With 30-item limit and no search, older notes are inaccessible.
- **No category filtering**: Notes list shows all notes mixed. No way to see "all partner notes" or "all bill notes" from the notes section.
- **No "attached notes" view per entity**: Tapping a bill shows bill details, but there's no button to "view all notes for this bill." The `📒 Note` button only ADDS a new note, not views existing ones.
- **Notes not shown in appointment detail**: Appointment detail shows `appt["notes"]` (the notes field on the appointment itself), but notes added via `notes:add:appt:{id}` are stored separately in the notes table. These detached notes are never displayed in the appointment detail view.

### What's BROKEN (implemented but doesn't work correctly):
- **Notes list shows raw `created_at` timestamp**: In `notes.py` line 74: `f"Created: {note['created_at']}"` — this is a raw SQLite datetime string like "2026-03-30 14:22:11", not a friendly date.
- **Notes list truncation is silent**: `_get_notes()` limits to 20 but the UI says "NOTES (N)" where N reflects the query count, not total. If user has more than 20 notes, they can never see the rest. No pagination.

### What needs typed input but should use buttons:
- **Note content**: This is inherently free-text. Acceptable. ✅

---

## APPOINTMENTS (`modules/appointments.py`)

### What was requested:
- Add appointments with title, category, date, time, notes, priority
- Button-based date picker — NO typed dates
- Category picker via buttons
- Priority/reminder level via buttons
- Skip should skip ONE item not entire section
- Inline edit and delete for all fields
- Smart reminders based on priority
- Show in Today view, week view, digests

### What's built and working:
- Full multi-step add flow: Title (typed) → Category (buttons) → Date (button date picker) → Time (typed with skip button) → Notes (typed with skip button) → Priority (buttons) → Save ✅
- Button date picker for add flow ✅
- Category picker fully button-based ✅
- Priority picker with up/down adjust buttons ✅
- Skip Time button ✅
- Skip Notes button ✅
- `appts:skip_time` skips ONE item (time) not the section ✅
- `appts:skip_notes` skips ONE item (notes) not the section ✅
- Inline edit: title, date (button date picker), time, notes, category (button picker), priority (button picker) — all accessible
- Delete with confirmation
- Mark Done / Reopen
- Smart reminders: priority 0=none, 1=[1d], 2=[1d, 0d], 3=[3d,1d,0d], 4=[7d,3d,1d,0d] ✅
- Follow-up reminder for high priority (≥3) on day-of
- Snooze 2hrs button on day-of reminders
- Shift conflict warning in reminders (if working tonight and appt ≤1 day away)
- Appointment data persisted to DB for restart recovery ✅
- Shows in Today view (7 days), week view, digests ✅
- `is_appt_midflow` guard in `button_router` prevents state wipe during category/priority buttons ✅

### What's MISSING (not implemented at all):
- **Time entry is still typed**: After the date picker, the bot says "What time? (e.g. '2pm', '14:00', '9:30am')" — this requires typing. There is no button-based time picker. A common time button row (8am, 10am, 12pm, 2pm, 4pm, 6pm, 8pm, 10pm, skip) was requested but not built.
- **Notes entry is typed**: Same as above — notes require typing. A "skip" button exists but typing is the only way to add notes.
- **Title is typed**: The appointment title is free-text entry with no button shortcuts.
- **Social appointment category + recovery day warning**: No code checks `category == "social"` + `is_recovery_day()` + `time < 17:00` and warns the user.
- **No "appointments before 5pm on recovery days" guard in add flow**: User could add a social appointment at 10am on their recovery day with zero warning.

### What's BROKEN (implemented but doesn't work correctly):
- **`_handle_date()` is dead code**: `appointments.py` line 415-444 defines `_handle_date()` which handles typed date input. But since the date picker is button-based (`apptdp:*`), the `AWAITING_APPT_DATE` state is never set anywhere in the creation flow. The date step goes directly to `date_pick_month_kb("apptdp")` from the `category:*` callback. `AWAITING_APPT_DATE` constant is defined but never assigned to `context.user_data["awaiting"]` in the current flow. `_handle_date()` is unreachable dead code. However, `handle_appt_text()` doesn't check for `AWAITING_APPT_DATE` anyway, so it's harmless but confusing.
- **Time parse for nocturnal user**: `_parse_time_loosely()` line 765-767: "Assume PM for small numbers without am/pm (nocturnal user)" — this assumes PM for hours < 8. So "2" becomes 14:00, "7" becomes 19:00. But "8" would NOT get this treatment and stays as 08:00, which may be wrong for a night-shift worker typing "8" meaning 8pm. The threshold is arbitrary.
- **Priority `_is_appt_midflow` guard in `bot.py` line 169-173**: The guard checks for specific prefixes `("category:", "skip_time", "skip_notes", "priority_ok", "priority_none", "priority_up", "priority_down")`. If the user presses "priority_ok" after a bot restart, `context.user_data` will be empty (title/date/category all lost), and `_save_with_priority()` will save garbage defaults ("Untitled", today's date, "other" category). There's partial DB persistence (`pending_appt_title`, `pending_appt_cat`) but `appt_date`, `appt_time`, `appt_notes`, `appt_priority` are in `context.user_data` only.

### What needs typed input but should use buttons:
- **Title**: Free-text — acceptable, but common appointment types (Doctor, Dentist, DMV, Court, Work, etc.) as quick buttons would help ADHD users.
- **Time**: Entirely typed. Should be a button grid of common times.
- **Notes**: Typed. Should have quick-note buttons ("Bring ID", "Bring insurance card", "Fasting required", etc.) plus free-text option.

---

## SCHEDULER / SUGGESTIONS (`modules/scheduler.py`, `modules/suggestions.py`)

### What was requested:
- Afternoon digest at appropriate time for night-shift worker
- Evening check-in
- Med nag until taken
- Bill nag on payday
- Quality-of-life suggestions in check-ins
- Weekly summary
- Appointment reminders based on priority
- Behavioral intelligence (Features 11-20 from spec)
- No social before 5pm on recovery days → sleep conflict warning exists
- Feature toggles respected

### What's built and working:
- Afternoon digest at 2pm ET (configurable via `DAILY_DIGEST_HOUR`)
- Evening check-in at 10pm ET (configurable via `EVENING_CHECKIN_HOUR`)
- Med nag every 2 hours during 5am-5pm window
- Bill nag on payday (Fridays) every 3 hours
- Weekly digest Sunday at noon ET
- Appointment reminders hourly 5am-5pm, threshold-based per priority
- Follow-up for high-priority appointments
- Snooze 2hrs functionality
- Suggestions module called in digests ✅
- Wellness checks (hydration, recovery day tips) ✅
- Partner nudge based on interaction frequency ✅
- Deadline nudge for creds and bills ✅
- Sleep conflict warning (appointment in sleep window next day) ✅
- All jobs respect feature toggles ✅
- `_already_sent` deduplication prevents repeat reminders same day ✅

### What's MISSING (not implemented at all):
- **Notification window is WRONG for night-shift worker**: All reminders fire between 5am-5pm ET (bot.py line 525-546). The user works 7pm-7am. Their sleep window is approximately 7am-3pm. Sending med nags at 5am, 7am, 9am is during or right before their sleep. The notification window should be ~3pm-10pm for a nocturnal user. This is hardcoded in `bot.py` setup_jobs(), not user-configurable.
- **No user-specific notification window**: `users` table has `notify_start`/`notify_end` columns, but `setup_jobs()` ignores them — all jobs are global, fixed-time. There is NO per-user notification window logic in the scheduler.
- **Behavioral intelligence (Features 11-20 from spec)**: Zero implementation. No interaction logging table, no response time tracking, no active hours detection, no feature usage frequency tracking, no skip pattern analysis, no adaptive message length, no micro-surveys. The behavioral-intelligence-spec.md describes 100 features; approximately 5-6 are partially implemented via `suggestions.py`.
- **Progressive profile building via micro-surveys**: Feature 7 from spec — after 3 days of usage, ask a single follow-up question. Not implemented at all.
- **"No Judgment Re-Entry"**: Feature 10 — if user disappears and comes back, welcome them without guilt. `start_command` says "Welcome back" but doesn't check how long they've been gone or show what's upcoming proactively.
- **`_send_weekly()` doesn't call `get_suggestions()`**: The weekly digest in `scheduler.py` lines 251-297 aggregates shift/bills/car/creds/appointments but NEVER calls `get_suggestions()`. Only `_send_digest()` (afternoon/evening) calls suggestions.
- **Partner nudge in scheduler**: `suggestions._partner_nudge()` is called in digests but there's no standalone push notification if a partner interaction is overdue. It only fires if the digest happens to be sent that day.
- **Daily reset is multi-user unsafe**: `daily_reset()` line 43: `conn.execute("UPDATE medications SET taken_today = 0")` — no `WHERE chat_id` filter. All users' medications reset together. Same for bills reset on line 45.

### What's BROKEN (implemented but doesn't work correctly):
- **Notification window hardcoded wrong for the target user**: Reminders 5am-5pm fire during sleep for a 7pm-7am shift worker who sleeps ~7am-3pm.
- **`bill_nag` fires every day that has a scheduled time, not just Fridays**: `bill_nag()` line 215-216: checks `if not is_payday(today()): return`. But `bill_nag` is registered in `setup_jobs()` line 529-530 with `run_daily` at hours 9, 12, 15 — it fires every day but returns early if not payday. This works correctly functionally but wastes job scheduler slots.
- **`appointment_reminder_check` during sleep window**: Runs hourly 5am-4pm ET (lines 541-546). For a sleeping user, this fires during their sleep window, potentially waking them with Telegram notifications.
- **`_maybe_followup` is not awaited correctly**: Line 350: `_maybe_followup(context, chat_id, appt, d)` — this is called without `await`. `_maybe_followup` is an `async def` function. This means the follow-up reminder is NEVER actually sent — the coroutine is created but never executed. **This is a silent, complete failure of the follow-up feature.**

### What needs typed input but should use buttons:
- The scheduler is automated, no user input needed. ✅

---

## ONBOARDING (`modules/onboarding.py`)

### What was requested:
- Questions should come slowly, not all at once at onboarding
- Minimal typing, mostly buttons
- Skip should skip ONE item not entire section
- Schedule picker: 7 buttons in one row (Sun-Sat), multi-week rotation support
- Back buttons
- Progress indicators
- 7p-7a as the primary/default night shift option

### What's built and working:
- Welcome screen with "Let's Set Up" / "Skip for Now" ✅
- Step progress indicator (Step X of 7) ✅
- Name entry (typed — only text field in early onboarding) ✅
- Shift type picker via buttons (7p-7a option listed first) ✅
- 7-button day picker in single row (Su Mo Tu We Th Fr Sa) ✅
- Multi-week rotation: after Week 1, asks "Add Week 2?" — supports N weeks ✅
- Back buttons between major sections ✅
- `onboard:skip_item` skips ONE item, not the entire section ✅
- Skip item returns to "another?" prompt, not straight to next section ✅
- Duplicate detection for partners/bills/meds/credentials ✅
- Full input validation (names, amounts, dates) ✅
- Car date picker (button-based via `onboard:ob_date:car:*`) ✅
- Credential expiry picker (button-based via `onboard:ob_date:cred:*`) ✅
- Partner relationship type picker ✅
- DB persistence for all multi-step entries (survives bot restarts) ✅
- Re-run onboarding from Settings ✅
- `12p-12a` shift option still exists (user said shift is 7p-7a, this is a wrong default but 7p-7a is listed)

### What's MISSING (not implemented at all):
- **Slow progressive onboarding**: The user said "questions can come slowly as you use the app." Onboarding still collects everything upfront (partners, bills, car, creds, meds). The behavioral spec Feature 1 says "ask ONLY two things" at onboarding. This is fundamentally not implemented — onboarding can be 7 sections long even if each section is skippable.
- **Self-selected segmentation** (Feature 3 from spec): "What do you most want help with?" with 3-4 buttons. Not implemented.
- **Blank-slate first action** (Feature 2 from spec): After finishing onboarding, user is sent to `main_menu_kb()`. No "Your first action: Add a bill" or context-specific prompt.
- **Celebration of first actions** (Feature 9 from spec): When user adds their first bill during onboarding, it just says "Added: [name]." No "Nice — I'll remind you 3 days before it's due" style ADHD-friendly reward message. (The message for credentials says "You can add license #, state, and CEU info from the detail view" — functional but not celebratory.)
- **Contextual feature discovery** (Feature 8 from spec): Features don't reveal themselves progressively through use — they're all available from the main menu immediately.
- **Onboarding section for appointments**: There is no onboarding section for appointments. Users discover it from the main menu.
- **12p-12a should be removed or corrected**: User explicitly said "Shift is 7p-7a NOT 12p-12a." The option `"🌙 Nights (12p-12a)"` still exists in `onboard_shift_type_kb()` in `keyboards.py` line 558. This is incorrect and could confuse new users.

### What's BROKEN (implemented but doesn't work correctly):
- **`onboard_progress_text()` for partners/bills/car/creds/meds sections**: These sections all display progress steps (3 through 7) but the actual text prompts for car/cred/med sections don't use `onboard_progress_text()` — they use hardcoded step strings. Looking at the code, `_dispatch_onboard_action()` for `add_car` section uses `onboard_progress_text('car_intro')` ✅ but several sub-prompts (e.g., "Another car item?", "Another credential?") do not show progress.
- **`onboard:days_done` requires at least 1 day selected**: Lines 471-476 show an alert if no days selected. But the Days picker keyboard (`onboard_days_kb`) always renders all 7 days unselected initially. If user immediately taps Done, the alert fires. This is correct behavior but potentially confusing — no instruction text says "tap the days you work" prominently enough.
- **Back navigation from schedule is incomplete**: `onboard:back:schedule_result` in `_handle_back()` takes user back to partners_intro, not back to the schedule confirmation. The label says "schedule_result" but it goes forward to partners. This is correctly intended as "I'm done with schedule" but the naming is confusing.
- **`_parse_date_loosely` vs `parse_date_loosely`**: `onboarding.py` exports `parse_date_loosely` (no leading underscore, returns tuple). `credentials.py` line 171 imports `_parse_date_loosely` (with underscore). The underscore version doesn't exist in the new onboarding code (it's a renamed function). This import would crash if that code path is ever hit.

### What needs typed input but should use buttons:
- **Name**: Typed — unavoidable.
- **Custom shift hours**: Typed (e.g., "3p-11p") — acceptable for the edge case.
- **Bill amount**: Typed number — could be made optional/skippable with fewer friction if a "$0 / Skip" button existed inline instead of requiring a typed "skip" word.
- **Partner name**: Typed — acceptable.
- **Credential name**: Typed — acceptable.
- **Medication name**: Typed — acceptable.
- **12p-12a option**: Should be REMOVED — user confirmed their shift is 7p-7a.

---

## SETTINGS (`modules/settings_handlers.py`, bot.py `handle_settings()`)

### What was requested:
- Backend settings panel to toggle features on/off
- Alter schedule option (accessible from today/week view)
- Schedule editor: week 1 and week 2 days
- Shift hours editor
- Override individual days (working today / off today)
- Notification time settings

### What's built and working:
- Settings menu with 6 options ✅
- Feature Toggles panel: 8 features (med reminders, bill reminders, appt reminders, afternoon digest, evening check-in, weekly digest, wellness checks, partner nudges) — all toggleable via buttons ✅
- Toggle state persisted to DB ✅
- Toggles respected by scheduler ✅
- Schedule editor: view current schedule as emoji grid, change shift hours, edit week 1 days, edit week 2 days ✅
- Week 1/2 day editor reuses onboard day picker (7-button row) ✅
- Override today/tomorrow as working/off — from Settings AND from Today/Week "Alter Schedule" button ✅
- Override persisted to `shift_overrides` table ✅
- Schedule displays 14-day grid with 🏥/🏠 ✅
- Re-run onboarding button ✅

### What's MISSING (not implemented at all):
- **Notification time settings are not editable**: `settings:notify` in `bot.py` line 393-400 shows "Notification window: 5 AM – 5 PM ET" with the message "(Editing notification times coming soon)". This is a placeholder. The `notify_start`/`notify_end` fields exist in the `users` table but are never used by the scheduler.
- **Payday settings are not editable**: `settings:payday` at line 402-407 shows "Payday: Every Friday" with "(Editing payday settings coming soon)". Placeholder. `users.payday_weekday` exists in DB but is hardcoded to Friday everywhere.
- **Timezone setting**: The `users.timezone` field exists but there is no UI to change it. Everything runs on hardcoded `America/New_York`.
- **No way to change display name**: Users can re-run onboarding to change their name but there's no "Edit my name" button in Settings.
- **Feature toggle for car reminders is missing**: The 8 feature toggles don't include car/admin reminders. Car events show in digests but can't be disabled separately.
- **Feature toggle for credential reminders is missing**: Similarly, no separate toggle for credential expiry reminders.
- **Partner check-in frequency per person is not a setting**: It's on each partner's detail page but not surfaced in global settings.
- **Override only covers today/tomorrow**: No way to override a specific future date without going day by day.

### What's BROKEN (implemented but doesn't work correctly):
- **`settings:edit_shift_type` requires typing**: `bot.py` line 341-345: sets `awaiting = "settings_shift_type"` and prompts "What are your shift hours? (e.g. '7p-7a', '7a-7p', '3p-11p')". This is the only setting that requires typed input in settings. Should be buttons like the onboarding shift type picker.
- **`settings:schedule` shows Week 1/Week 2 correctly but the "Change Shift Hours" button leads to typed input**: Inconsistent with the rest of the settings panel which is button-driven.
- **Override from "Alter Schedule" (today view) vs "Override Shift Day" (settings) are separate paths**: Both write to `shift_overrides` table with the same logic. But "Alter Schedule" (`alter:*` prefix) returns to `today_actions_kb()` while Settings override (`settings:override_on/off:*`) returns to `settings_kb()`. The duplication means two code paths to maintain for the same feature.
- **`settings:schedule` displays schedule grid as monospace text**: Line 329-333 in `bot.py` uses Unicode characters to draw a grid, but Telegram message formatting without `parse_mode="Markdown"` means the `edit_message_text` call at line 339 doesn't preserve spacing. The grid may not align properly.

### What needs typed input but should use buttons:
- **Shift hours editing**: Should reuse `onboard_shift_type_kb()` with preset options + custom fallback, not a raw text prompt.

---

## CROSS-CUTTING CONCERNS (not specific to one module)

### What was requested:
- Button-first UX throughout
- Inline edit and delete for every parameter, every user
- Gathering data on how users answer (behavioral intelligence)
- Skip should skip ONE item not entire section

### What's built and working:
- Universal field editor (`field_editor.py`) handles inline editing for bills, car, creds, partners, meds, appointments ✅
- Date picker routes through field_editor for all date fields ✅
- Delete confirmation dialogs in all modules ✅
- `onboard:skip_item` skips ONE item ✅
- `_clear_input_state()` prevents stale state bugs ✅
- DB persistence for multi-step flows in car, creds, appointments ✅

### What's MISSING globally:
1. **Behavioral intelligence system**: The 100-feature spec is essentially unimplemented. No interaction logging table exists. Features 11-30 (behavioral learning engine) require an `interaction_log` table and a processing layer that doesn't exist anywhere in the codebase.
2. **Per-user notification windows**: `notify_start`/`notify_end` in `users` table are set but never used. All reminders fire at globally hardcoded times.
3. **2 dates/week cap**: Requested explicitly, not implemented anywhere.
4. **Recovery day social restriction**: Requested explicitly, not implemented in any scheduling or warning flow.
5. **Micro-surveys / progressive profile building**: Zero implementation.
6. **Multi-user support**: Multi-user is partially supported (all tables have `chat_id`) but the `daily_reset()` fires globally without per-user filters — it could cause incorrect behavior if multiple users have different reset dates.
7. **No "share" or "export" functionality** for the productization goal.

### What's BROKEN globally:
1. **`daily_reset()` missing WHERE clause**: `UPDATE medications SET taken_today = 0` and `UPDATE bills SET paid_this_cycle = 0` — no `WHERE chat_id`. Affects all users simultaneously.
2. **`_parse_date_loosely` import inconsistency**: `credentials.py` imports `_parse_date_loosely` from `onboarding` (with underscore), but onboarding exports `parse_date_loosely` (no underscore). This is a latent crash.
3. **`_maybe_followup` not awaited**: `scheduler.py` line 350 calls `_maybe_followup(...)` without `await`. This is an async function — the followup reminder is **completely silently non-functional**.
4. **Override bypass in week_view and partners**: Both call `is_work_day()` directly instead of `is_working()` which checks overrides first.

---

## SUMMARY TABLE

| Module | Core Features | Button-First | Inline Edit/Delete | Major Missing | Critical Bugs |
|--------|--------------|-------------|-------------------|---------------|---------------|
| Today/Tonight | ✅ Working | ✅ | N/A | Suggestions not in Today view; social/recovery guard | Dec overflow in bill due |
| Week View | ✅ Working | ✅ | N/A | Override bypass; week# indicator | Override bypass (silent wrong data) |
| Bills | ✅ Working | ⚠️ Add is typed | ✅ | Add flow all-typed; autopay unusable | Bill creation not DB-persisted |
| Partners | ✅ Working | ✅ | ✅ | 2-dates/week cap; recovery guard; override bypass | Schedule ignores overrides |
| Car | ✅ Working | ✅ | ✅ | No recurring items; no history view | Minor: done+list sends 2 messages |
| Credentials | ✅ Working | ✅ | ✅ | CEU UI; state picker | `creds_list_kb` crash on null expiry; import bug |
| Meds | ✅ Working | ⚠️ Add is typed | ✅ | Refill reminder; freq picker | `AWAITING_MED_EDIT` dead code; followup reminder dead |
| Notes | ✅ Working | ✅ | ❌ No editing | No note editing; no entity note view | Notes list truncates silently |
| Appointments | ✅ Working | ⚠️ Time/notes typed | ✅ | Time picker buttons; social/recovery guard | `_maybe_followup` not awaited; `_handle_date` dead code |
| Scheduler | ✅ Mostly | N/A | N/A | Notification times wrong for night shift; behavioral intelligence | Followup never fires; global reset no chat_id filter |
| Suggestions | ✅ Working | N/A | N/A | Not called from Today view; weekly digest doesn't call it | — |
| Onboarding | ✅ Working | ✅ | N/A | Progressive slow onboarding; 12p-12a should be removed | `_parse_date_loosely` import crash |
| Settings | ✅ Partial | ⚠️ Shift hours typed | N/A | Notification times not editable; payday not editable; timezone not editable | Shift hours editing requires typing |

---

*Generated by full code audit, April 1 2026. All findings based on actual code reading, not assumptions.*
