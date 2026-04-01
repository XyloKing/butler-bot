# Butler Bot QA Report
**Version:** 2.2.0-ux-overhaul  
**Tested:** 2026-04-01  
**Method:** Full static code trace of every module, callback path, and edge case. Live bot confirmed running (API /getMe + /getWebhookInfo verified, messages deliverable).

---

## CRITICAL BUGS (will crash or break flow)

### [APPOINTMENTS] `appts:delete` silently fails when appointment not found
**File:** `modules/appointments.py` line 117–129  
**Issue:** The `delete` action fetches the appointment and only edits the message `if appt:`. There is **no `else` clause**. If the appointment doesn't exist (deleted in another session, or stale message), the callback is answered (spinner stops) but the message is left unchanged with old buttons still showing. The user has no indication anything happened and remains stuck on the stale view.  
**Fix:** Add `else: await query.edit_message_text("Appointment not found.", reply_markup=back_to_menu_kb())`

---

### [BILLS / CREDENTIALS] Dead edit-value handlers that can never be reached (unreachable state)
**File:** `modules/bills.py` lines 229–255; `modules/credentials.py` lines 173–193  
**Issue:**  
- `AWAITING_BILL_EDIT_VALUE = "bill_edit_value"` is defined and checked in `handle_bill_text`, but **this state string is never set anywhere in the codebase**. The `bills:editfield` callback routes directly to `start_field_edit()` (field_editor), which sets `awaiting="field_edit"`, not `"bill_edit_value"`. Similarly `AWAITING_BILL_EDIT_FIELD` is never set.  
- Same pattern in `credentials.py`: `AWAITING_CRED_EDIT_VALUE = "cred_edit_value"` is checked but never set.  
- `edit_bill_id`, `edit_bill_field`, `edit_cred_id`, `edit_cred_field` are popped in `_clear_input_state()` in bot.py, but are never stored by any callback.  

**Impact:** These handlers are completely dead code. Any future developer adding an old-style edit flow could accidentally trigger confusing behavior. Not a runtime crash, but these handlers shadow nothing currently.

---

## MEDIUM BUGS (wrong behavior, doesn't crash)

### [BILLS] `handle_bill_text` always shows wrong paid status after field edit
**File:** `modules/bills.py` line 253  
**Issue:** In the legacy (dead) `AWAITING_BILL_EDIT_VALUE` handler, `bill_detail_kb(bill_id, False)` hardcodes `False` for the paid status. Since this handler is unreachable via the current flow (bills use `field_editor` now), this is **not a live bug** — but if the code were ever re-activated, a paid bill would show "Mark PAID" instead of "Mark Unpaid" after editing.  
**Status:** Dead code bug, no current user impact.

---

### [CAR / MEDS / CREDENTIALS] Back to menu instead of back to list after key actions
**Files:**  
- `modules/car.py` line 42: `car:done` → `back_to_menu_kb()` (not car list)  
- `modules/credentials.py` line 50: `creds:renewed` → `back_to_menu_kb()` (not creds list)  
- `modules/meds.py` line 52: `meds:take` (individual take) → `back_to_menu_kb()` (not meds list)  

**Issue:** After marking a car item done, renewing a credential, or taking a single med, the user is dropped to the main menu rather than back to the item's list. This is inconsistent — `meds:all_taken` also goes to back_to_menu, but `bills:paid` returns to the bills list. The inconsistency means extra taps to continue working in the same module.

---

### [APPOINTMENTS] Reminder action buttons (remind_done, remind_later, snooze2h) leave user stranded
**File:** `modules/appointments.py` lines 227–252  
**Issue:** All three reminder response actions (`appts:remind_done`, `appts:remind_later`, `appts:snooze2h`) edit the reminder message to a confirmation text **with no `reply_markup`**. This destroys all buttons on the message. The user must type `/menu` to navigate further. There is no back button or follow-up keyboard.  
**Affected callbacks:** `appts:remind_done`, `appts:remind_later`, `appts:snooze2h`  
**Fix:** Add `reply_markup=back_to_menu_kb()` to each of the three `edit_message_text` calls.

---

### [NOTES] No keyboard after `notes:add:today` in today_actions_kb
**File:** `keyboards.py` line 167; `modules/notes.py` line 110–113  
**Issue:** `notes:add:today` sets `context.user_data["note_category"] = "today"`. When the note is saved, `handle_note_text` sends "📒 Saved." with only a `back_to_menu_kb()`. The category `"today"` is non-standard (valid categories in notes are `general`, `bill`, `car`, `partner`, `cred`, `med`). The note is saved fine with `category="today"`, but:
1. Notes filtering/display by category may not handle `"today"` as expected.
2. The user is dropped to the main menu after saving.  
**Minor risk:** Consistent with overall UX pattern but `"today"` as a category name is semantically odd.

---

### [PARTNERS] `partners:schedule` when no shift configured shows all 7 days as free
**File:** `modules/partners.py` lines 130–163  
**Issue:** When no shift is configured for the user, `is_work = False` for every day, so all 7 days appear as free. The first 5 are shown as scheduling options. This is technically correct behavior (no shift = always free) but the message doesn't clarify there is no schedule set, which could confuse users who haven't configured their schedule yet.

---

### [WEEK VIEW] `week:next` and `week:prev` pass stale offset instead of displayed offset
**File:** `modules/week_view.py` lines 25–30  
**Issue:** The nav buttons embed `{offset}` (the value from the current call's `_show_week`), so navigation IS mathematically correct (each button increments/decrements by 7 from the last-displayed week). However, if a user has the week view open and the week changes at midnight, the "current" offset in the buttons no longer matches reality — tapping "This Week" still works because it hardcodes `week:view:0`, but the prev/next buttons could theoretically show the wrong week relative to actual today.  
**Severity:** Low — this is a natural consequence of stateless button design and only matters if a message is left open overnight.

---

### [FIELD EDITOR] `notes` field has no human-readable prompt
**File:** `modules/field_editor.py` line 86  
**Issue:** `FIELD_PROMPTS` does not include a `"notes"` key (only `"content"` for the notes table). When `appts:editfield:ID:notes` or `meds:editfield:ID:notes` is pressed, the fallback prompt `f"New value for notes?"` is used. This works but is less polished than other field prompts.  
**Affected edits:** appointment notes, med notes, bill notes (via any future path using field_editor for notes).

---

## MINOR ISSUES (cosmetic, UX)

### [NOTES] No note editing — only delete
**File:** `modules/notes.py` / `keyboards.py`  
Notes have no edit button in `_show_note_detail`. Users can only delete and re-add. Intentional design choice likely, but worth documenting.

### [BILLS] `bills:confirm_delete` returns to `back_to_menu_kb` not bills list
**File:** `modules/bills.py` line 81  
After deleting a bill, user lands at the main menu instead of the bills list. Minor navigation friction.

### [APPTS] `appts:confirm_delete` sends a new reply then new list (double messages)
**File:** `modules/appointments.py` lines 131–139  
`confirm_delete` calls `edit_message_text("🗑 Deleted.")` then immediately calls `_show_appts_list(send_new=True)` which sends *another* new message. This produces two messages for one action: the "Deleted." text and then the full appointments list.

### [SCHEDULER] Unused import `followup_kb`
**File:** `modules/scheduler.py` line 18  
`followup_kb` is imported from `keyboards` but **never called** anywhere in `scheduler.py`. It was presumably removed during refactoring. No runtime impact (import succeeds), but it's dead code.

### [KEYBOARDS] `followup_kb` generates unhandled `{category}:snooze:{id}` callback
**File:** `keyboards.py` lines 514–521  
`followup_kb` generates buttons with `callback_data=f"{category}:snooze:{item_id}"`. Since `followup_kb` is never called, this is inert. However, if it were ever used with `category="appts"`, it would produce `appts:snooze:ID` — and **`appts_callback` only handles `snooze2h`**, not `snooze`. The button would trigger the generic "Unknown action" fallback.

### [CAPTURE] Legacy `capture:appointment` handler is dead code
**File:** `bot.py` lines 289–295  
`handle_capture` has an `elif action == "appointment"` branch that sets `awaiting="appt_title"`. However, `capture_menu_kb()` routes to `appts:add` directly (not `capture:appointment`). No button generates `capture:appointment` in the current UI. The handler works correctly if ever triggered but is unreachable through normal navigation.

### [SETTINGS] `settings:notify` and `settings:payday` show info only, no actual editing
**File:** `bot.py` lines 395–409  
Both "Notification Times" and "Payday Settings" display hardcoded text with "(Editing coming soon)" notes. They return to `settings_kb()` which is correct, but users may be confused that they can't actually edit these values.

### [PARTNERS] `partner_edit_name` awaiting state uses custom key, not field_editor
**File:** `modules/partners.py` lines 331–340  
The `"partner_edit_name"` awaiting state in `handle_partner_text` is checked but **never set** by any current callback (the `partners:editfield:{id}:name` callback routes through `field_editor`, which uses `awaiting="field_edit"`). This is additional dead code in the partners text handler.

### [MEDS] `AWAITING_MED_EDIT` handler uses text-split heuristic for parsing
**File:** `modules/meds.py` lines 170–188  
The `AWAITING_MED_EDIT = "med_edit"` state is **never set** by any current callback (meds editfield goes through field_editor). This handler is dead code. Additionally, its parsing logic (`text.rsplit(" ", 1)` to split name and dosage) is fragile if ever re-activated.

### [CAR] `car:addtype` action's `item_id` is always `None` (by design, not a bug)
**File:** `modules/car.py` lines 27–28, 64–83  
`item_id = int(parts[2]) if ... parts[2].isdigit() else None` — for `car:addtype:oil_change`, `parts[2]` is `"oil_change"` (not a digit), so `item_id=None`. This is intentional — `addtype` reads `parts[2]` directly as `event_type`, not as an ID. Not a bug, but the dual-use of `parts[2]` is confusing.

### [BILLS] `bills:payday` sends payday summary with empty list if no bills
**File:** `modules/bills.py` lines 146–162  
If there are no unpaid bills, the payday summary shows only the header and total line with `$0.00`. Functional but could say "No unpaid bills — you're all clear! 🎉" for better UX.

---

## DEAD CODE / UNREACHABLE

1. **`handle_bill_text` AWAITING_BILL_EDIT_VALUE branch** (`modules/bills.py` lines 229–255) — State `"bill_edit_value"` is never set. Dead since field_editor replaced the old inline edit flow.

2. **`handle_cred_text` AWAITING_CRED_EDIT_VALUE branch** (`modules/credentials.py` lines 173–193) — Same as above for credentials.

3. **`handle_partner_text` `partner_edit_name` branch** (`modules/partners.py` lines 331–340) — State `"partner_edit_name"` is never set.

4. **`handle_med_text` AWAITING_MED_EDIT branch** (`modules/meds.py` lines 170–188) — State `"med_edit"` is never set.

5. **`capture:appointment` handler** (`bot.py` lines 289–295) — No button generates this callback in current UI. `capture_menu_kb()` routes to `appts:add` directly.

6. **`followup_kb()` function** (`keyboards.py` lines 514–521) — Defined and imported in `scheduler.py` but never called.

7. **Constants `AWAITING_BILL_EDIT_FIELD`, `AWAITING_CRED_EDIT_FIELD`** — Defined but never used in set operations.

8. **`_clear_input_state` clears `edit_bill_id`, `edit_bill_field`, `edit_cred_id`, `edit_cred_field`** (`bot.py` lines 106–121) — These keys are never stored anywhere, so the `.pop()` calls are no-ops.

---

## VERIFIED WORKING

**Core routing:**
- `button_router` correctly routes all known prefixes: `menu`, `today`, `week`, `bills`, `partners`, `car`, `creds`, `meds`, `notes`, `appts`, `capture`, `settings`, `onboard`, `datepick`, `pdatepick`, `alter`
- `noop` callback handled correctly (returns immediately, no error)
- `_clear_input_state` fires on every button press except settings day-picker and appt mid-flow buttons — correct
- Unknown callback prefixes produce "Unknown action. Tap /menu." message gracefully

**Today view (`today:view`):**
- Correctly shows shift status, meds, bills due within 3 days, car items within 30 days, credentials within 60 days, partner dates within 14 days, appointments within 7 days, today's notes
- Handles all NULL fields gracefully (no bill amount, no due_date)
- Empty state: shows "Nothing urgent. Enjoy your day. 🫡"
- `_bill_due_delta` correctly handles bills with only `due_date` (no `due_day`)
- `_resolve_partner_date` correctly handles MM-DD recurring and ISO one-off dates

**Week view (`week:view`, `week:next`, `week:prev`):**
- Sunday-first calculation: `sun_offset = (d.weekday() + 1) % 7` correctly places Sunday first
- Navigation offsets are mathematically consistent
- "This Week" button only appears when `offset != 0`
- Markdown code block wrapping is safe for calendar content
- All event types (bills, payday, car, partner dates, credentials, appointments) correctly aggregated by date

**Bills module:**
- `bills:view` with empty data: shows "No bills yet" with Add/Payday/Back buttons
- `bills:detail`, `bills:paid`, `bills:unpaid`, `bills:add`, `bills:payday` all route correctly
- `bills:editfield` correctly routes through `field_editor` with `start_field_edit()`
- `bills:delete` → `confirm_delete_kb("bills", id)` → `bills:confirm_delete` works
- `bills:payday` shows summary with correct total
- Multi-step add flow (name → amount → due_day) with skip support works

**Partners module:**
- `partners:view`, `partners:detail`, `partners:add` all work
- `partners:picktype` → `relationship_type_kb` → `partners:settype` → DB update → detail view
- `partners:pickfreq` → `interaction_freq_kb` → `partners:setfreq` → DB update → detail view
- `partners:adddate:birthday:{id}` → `pdatepick` MM-DD picker → save correctly
- `partners:adddate:anniversary:{id}` → `pdatepick` MM-DD picker → save correctly
- `partners:schedule` → free day picker → `partners:booked` → saves date_night → detail
- `partners:editfield` → `field_editor` → saves, shows partner detail
- `partners:delete` → `confirm_delete_kb` → `partners:confirm_delete` → deletes partner + dates
- Back buttons present: `relationship_type_kb`, `interaction_freq_kb`, `partner_detail_kb`, `partners_list_kb`

**Partner date picker (`pdatepick:*`):**
- `pdatepick:{id}:{type}:mmdd_m:{month}` → day picker ✓
- `pdatepick:{id}:{type}:mmdd_d:{MM-DD}` → saves to DB ✓
- `pdatepick:{id}:{type}:mmdd_back` → back to month picker ✓
- `pdatepick:{id}:{type}:cancel` → back to detail ✓
- `pdatepick:{id}:{type}:yr:{year}` → show months for year ✓
- `pdatepick:{id}:{type}:month:{num}:{year}` → day picker ✓
- `pdatepick:{id}:{type}:day:{YYYY-MM-DD}` → saves to DB ✓

**Field editor + date picker (`datepick:*`):**
- Date fields (`due_date`, `expiry_date`, `refill_date`, `event_date`) launch button-based date picker
- Non-date fields use text prompt correctly
- `datepick:{module}:{id}:{field}:yr:{year}` → months for year ✓
- `datepick:{module}:{id}:{field}:month:{num}:{year}` → day grid ✓
- `datepick:{module}:{id}:{field}:day:{YYYY-MM-DD}` → DB update + return to detail ✓
- `datepick:{module}:{id}:{field}:cancel` → return to detail ✓
- Numeric/time/nullable field parsing in `handle_field_edit_text` correct
- `_send_detail_view` correctly re-fetches DB state for all modules: bills, car, creds, partners, meds, appts

**Car module:**
- `car:view`, `car:detail`, `car:add` → type picker → `car:addtype:{type}` → text input ✓
- `car:done`, `car:undone`, `car:editfield`, `car:delete`, `car:confirm_delete` all work
- `car:addtype` correctly reads `parts[2]` for event type (not item_id)
- Empty list handled gracefully

**Credentials module:**
- `creds:view`, `creds:detail`, `creds:add`, `creds:renewed` all work
- `creds:editfield` routes to field_editor correctly
- `creds:delete` → `confirm_delete_kb` → `creds:confirm_delete` works
- Date field `expiry_date` launches date picker via field_editor

**Medications module:**
- `meds:view`, `meds:detail`, `meds:add` (name → dosage flow) work
- `meds:all_taken` and `meds:taken` both mark all medications for chat as taken
- `meds:take` marks individual med as taken
- `meds:untake` unmarks individual med, returns to detail
- `meds:editfield` routes to field_editor
- `meds:delete` → `confirm_delete_kb` → `meds:confirm_delete` works
- `meds:editfield:{id}:refill_date` correctly launches date picker

**Notes module:**
- `notes:view`, `notes:detail`, `notes:add:general`, `notes:add:today` all work
- Notes attachable from any module: `notes:add:bill:{id}`, `notes:add:car:{id}`, `notes:add:partner:{id}`, `notes:add:cred:{id}`, `notes:add:med:{id}`
- `notes:delete` works (no confirmation dialog — intentional quick delete)
- Empty state: "No notes yet" with Add button

**Appointments module:**
- `appts:view`, `appts:add`, `appts:detail` all work
- Full creation flow: title → category picker → date text → time text/skip → notes text/skip → priority picker → save ✓
- `appts:category:{cat}` mid-flow button correctly preserved from `_clear_input_state` exemption
- `appts:priority_ok`, `appts:priority_none`, `appts:priority_up`, `appts:priority_down` all work
- `appts:editfield` → field_editor → correct detail shown after edit
- `appts:editcategory` → category picker → `appts:setcategory` → DB update → new detail ✓
- `appts:editpriority` → priority picker → `appts:setpriority` → DB update → new detail ✓
- `appts:done`, `appts:undone` work, both send new messages showing updated list
- `appts:confirm_delete` works (note: sends two messages — "Deleted." + new list)
- Scheduler reminder callbacks: `appts:remind_done`, `appts:remind_later`, `appts:snooze2h`, `appts:detail` all handled
- `appts:remind_view` correctly routes to `_show_appt_detail_new`

**Alter schedule (`alter:*`):**
- `alter:start` → `alter_schedule_kb()` ✓
- `alter:override_on:0`, `alter:override_on:1`, `alter:override_off:0`, `alter:override_off:1` → DB upsert into `shift_overrides` → confirmation with `today_actions_kb()` ✓
- Back button on `alter_schedule_kb` → `today:view` ✓
- "Edit Full Schedule" → `settings:schedule` ✓

**Settings module:**
- `settings:view` → settings menu ✓
- `settings:schedule` → shows shift info + 14-day grid + `schedule_edit_kb` ✓
- `settings:edit_shift_type` → text input → updates DB ✓
- `settings:edit_w1` / `settings:edit_w2` → day picker (reuses onboard day picker) → Done → DB update ✓
- `settings:override` → `override_day_kb` → 4 override buttons → DB upsert ✓
- `settings:notify` → info text (editing not yet implemented)
- `settings:payday` → info text (editing not yet implemented)
- `settings:toggles` → `feature_toggles_kb` with DB-backed toggle state ✓
- `settings:toggle:{key}` → toggles DB value → refreshes toggle view ✓
- Day picker state isolation: `_is_settings_day_pick` exemption prevents `_clear_input_state` from wiping `settings_editing` ✓

**Settings day picker (settings → Week 1/2 → onboard day callbacks):**
- `settings_editing` set to `"week1"` or `"week2"` before entering day picker ✓
- `onboard:day:{num}` toggled correctly while `settings_editing` is active ✓
- `onboard:days_done` saves to correct `week1_days` or `week2_days` column ✓
- After save, `settings_editing` and `settings_selected_days` are cleared ✓

**Feature toggles:**
- Default ON when not in DB ✓
- Toggle persists to DB ✓
- First toggle (not in DB) sets to OFF (was implicitly ON) ✓

**Onboarding (`onboard:*`):**
- `onboard:start` → name step ✓
- `onboard:skip` → skip for now, goes to main menu ✓
- `onboard:skip_item` → skip current item in onboarding ✓
- Back buttons routed through `_handle_back` ✓
- `onboard:back:name` → back to name step ✓
- `onboard:back:shift_type` → back to shift type picker ✓
- Day picker in onboarding: `onboard:day:{num}`, `onboard:days_done` ✓
- All shift type presets: `onboard:shift:7p-7a`, `7a-7p`, `12p-12a`, `rotating`, `custom` ✓

**Keyboard correctness:**
- All `back_button_row()` calls use `menu:main` — handled by `handle_menu` ✓
- `back_to_menu_kb()` uses `menu:main` ✓
- `confirm_delete_kb("category", id)` generates `{category}:confirm_delete:{id}` — all modules handle `confirm_delete` ✓
- `noop` buttons (header labels in grids) never crash — handled at top of `button_router` ✓
- 14-day grid schedule uses `noop` for all cells — correct ✓

**Database:**
- Schema: All NOT NULL constraints on required fields (due_date, expiry_date, event_date) ✓
- Migrations: `category`, `priority`, `reminder_level` on appointments added safely via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern ✓
- `relationship_type` and `interaction_freq` columns added to partners via migration ✓
- WAL mode enabled for concurrency ✓
- Foreign keys enforced ✓

---

## SUMMARY TABLE

| Severity | Count | Items |
|----------|-------|-------|
| Critical | 1 | `appts:delete` silent fail on missing appointment |
| Medium | 5 | Stranded users after reminder actions; wrong back destinations (car/creds/meds:take); `appts:confirm_delete` double-message; dead edit handlers with incorrect paid status (inactive) |
| Minor | 9 | Notes prompt fallback; no note editing; followup_kb dead; capture:appointment dead; settings not editable (notify/payday); partner_edit_name dead state; reminder action keyboards missing; notes:add:today unusual category; bills delete back to menu |
| Dead Code | 8 | Multiple legacy awaiting states, followup_kb, capture:appointment, _clear_input_state no-ops |
