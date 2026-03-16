"""
Butler Bot Configuration
All settings and defaults in one place.
"""
import os
from datetime import time

# ─── Telegram ────────────────────────────────────────────────
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# ─── Timezone ────────────────────────────────────────────────
TIMEZONE = "America/New_York"

# ─── Notification Windows (ET) ───────────────────────────────
# Nocturnal user — active notifications 5 AM – 5 PM
# Afternoon + evening check-ins preferred
NOTIFY_START = time(5, 0)
NOTIFY_END   = time(17, 0)

# Digest delivery
DAILY_DIGEST_HOUR   = 14    # 2 PM ET — afternoon wake-up check-in
EVENING_CHECKIN_HOUR = 22   # 10 PM ET — night shift check-in
WEEKLY_DIGEST_DAY   = 6     # Sunday
WEEKLY_DIGEST_HOUR  = 12    # Noon ET

# ─── Work Schedule Defaults (starting 2026-03-30) ────────────
SCHEDULE_ANCHOR = "2026-03-30"  # Monday of week-1
WEEK1_DAYS = [0, 1, 5]         # Mon=0, Tue=1, Sat=5
WEEK2_DAYS = [6, 2, 3]         # Sun=6, Wed=2, Thu=3
SHIFT_START = time(12, 0)      # noon
SHIFT_END   = time(0, 0)       # midnight

# ─── Database ────────────────────────────────────────────────
DATABASE_PATH = os.environ.get("DATABASE_PATH", "butler.db")

# ─── Payday ──────────────────────────────────────────────────
PAYDAY_WEEKDAY = 4  # Friday
