# Fix Plan — Prioritized Implementation Order

## PHASE 1: Critical Bugs (must fix, things are silently broken)

1. `_maybe_followup` not awaited in scheduler.py:350 — followup reminders NEVER fire
2. `daily_reset()` missing WHERE chat_id — multi-user unsafe
3. Week view + partner scheduling bypass shift overrides — use is_working() instead of is_work_day()
4. December bill due date overflow crash in today.py
5. `_parse_date_loosely` import crash in credentials.py (dead code but still broken)
6. `creds_list_kb` crash on null expiry_date — add try/except guard

## PHASE 2: Wrong Behavior (user-facing issues)

7. Notification window wrong for night shift — hardcoded 5am-5pm, should respect user's notify_start/notify_end
8. Suggestions not showing in Today view (only in scheduled digests)
9. Weekly digest doesn't call get_suggestions()
10. Settings shift hours editor requires typing — should use onboard_shift_type_kb()
11. Remove 12p-12a shift option from onboarding (user confirmed 7p-7a)
12. Greeting logic ignores shift schedule (says "good morning" during sleep)
13. Week view doesn't show which rotation week (Week 1 / Week 2)
14. Partner emoji in week view uses raw emoji not relationship_type

## PHASE 3: Missing Features (requested but not built)

15. 2 dates/week cap + display in Today/Week/Partner views
16. Recovery day social guard — warn when scheduling social stuff before 5pm on post-shift day
17. Bill add flow: button shortcuts for common bills + frequency picker buttons
18. Appointment time picker: button grid of common times
19. Med frequency picker: buttons instead of typed
20. Target dates per month: buttons (1/2/3/4) instead of typed
21. Bill creation data persisted to DB (like car/creds)
22. Onboarding partner flow: ask frequency after type (currently skips it)
