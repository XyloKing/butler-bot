# Track B: Heartbeat + Proactive Features — Changes Summary

## Files Modified

### modules/scheduler.py
- Added `morning_heartbeat()` — proactive wake-up message at 3 PM ET
- Added `_send_heartbeat()` — builds shift-aware greeting with ONE most-urgent item
- Added `_most_urgent_item()` — priority order: appointments → bills → untaken meds
- Added transition day protection in heartbeat (appends sleep-rhythm warning)
- Updated `daily_reset()` — tracks med streak before resetting taken_today flags
- Added `import random` for greeting variation

### modules/today.py
- Enhanced `_handle_metime()` with transition day detection
- Shows "🔄 Transition day" context with recovery windows and schedule adjustment tips

### modules/notes.py
- Added `TASK_WORDS` set and `_sounds_like_task()` for detecting task-like notes
- Added `_break_into_steps()` — generates ADHD-friendly breakdowns for common task types
- Modified `handle_note_text()` — offers breakdown when note sounds like a task
- Added `notes:breakdown:{id}` callback handler — shows numbered step list
- Moved InlineKeyboardButton/InlineKeyboardMarkup to module-level imports

### modules/meds.py
- Added `STREAK_MESSAGES` dict for milestone celebrations (3, 7, 14, 30 days)
- Added `_check_streak_celebration()` — returns message at milestones, None otherwise
- Modified `taken`/`all_taken` handlers to show streak celebration when all meds done
- Individual `take` handler now checks if all meds are done and shows celebration

### bot.py
- Imported `morning_heartbeat` from scheduler
- Registered heartbeat job in `setup_jobs()` at 3 PM ET daily

### keyboards.py
- Added "🌅 Morning Heartbeat" to `feature_toggles_kb()`

### database.py
- Added migration for `med_streak INTEGER DEFAULT 0` column on users table

### modules/partners.py
- Fixed pre-existing bug: removed shadowed local `from telegram import` that caused UnboundLocalError in Python 3.13

### test_full_flow.py
- Added 10 new tests covering all new features:
  - Heartbeat with no data (empty user)
  - Heartbeat finding appointments
  - Heartbeat finding untaken meds
  - Task breakdown detection logic
  - Task breakdown full callback flow
  - Short notes don't trigger breakdown
  - Med streak column migration
  - Med streak celebration at milestones
  - Morning heartbeat in feature toggles
  - New callback data within 64-byte limit

## Test Results
- 35 tests total: **35 passed, 0 failed**
- All 25 original tests still pass
- All 10 new tests pass
- Import check passes
- Syntax check passes on all modified files
