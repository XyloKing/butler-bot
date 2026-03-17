"""
SQLite database layer – single file, zero config.
"""
import sqlite3
import json
from contextlib import contextmanager
from config import DATABASE_PATH

SCHEMA = """
-- ═══════════════════════════════════════════════════════
-- USER PROFILES (multi-user support for sharing)
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS users (
    chat_id         INTEGER PRIMARY KEY,
    display_name    TEXT,
    timezone        TEXT    DEFAULT 'America/New_York',
    onboarded       INTEGER DEFAULT 0,
    onboard_step    TEXT,                       -- tracks where they are in onboarding
    onboard_data    TEXT,                       -- JSON blob of partial onboarding answers
    notify_start    TEXT    DEFAULT '05:00',
    notify_end      TEXT    DEFAULT '17:00',
    payday_weekday  INTEGER DEFAULT 4,          -- Friday
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- WORK SCHEDULE
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS shifts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL REFERENCES users(chat_id),
    shift_type  TEXT    DEFAULT '12p-12a',      -- descriptor
    anchor_date TEXT,                           -- ISO date of week-1 Monday
    week1_days  TEXT,                           -- JSON array e.g. [0,1,5]
    week2_days  TEXT,                           -- JSON array e.g. [6,2,3]
    created_at  TEXT    DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- BILLS
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS bills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL REFERENCES users(chat_id),
    name            TEXT    NOT NULL,
    amount          REAL,
    due_day         INTEGER,                    -- day-of-month (1-31) or NULL
    due_date        TEXT,                       -- specific next-due ISO date
    frequency       TEXT    DEFAULT 'monthly',
    autopay         INTEGER DEFAULT 0,
    paid_this_cycle INTEGER DEFAULT 0,
    account_user    TEXT,                       -- username / account # (encrypted later)
    notes           TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- CAR MAINTENANCE
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS car_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL REFERENCES users(chat_id),
    event_type  TEXT    NOT NULL,
    description TEXT,
    due_date    TEXT    NOT NULL,
    mileage     INTEGER,
    done        INTEGER DEFAULT 0,
    notes       TEXT,
    created_at  TEXT    DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- PROFESSIONAL CREDENTIALS
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS credentials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL REFERENCES users(chat_id),
    name            TEXT    NOT NULL,
    issuing_body    TEXT,
    credential_num  TEXT,
    state           TEXT,
    expiry_date     TEXT    NOT NULL,
    renewal_url     TEXT,
    ceu_required    INTEGER DEFAULT 0,
    ceu_completed   INTEGER DEFAULT 0,
    renewed         INTEGER DEFAULT 0,
    notes           TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- PARTNERS & DATES
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS partners (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL REFERENCES users(chat_id),
    name        TEXT    NOT NULL,
    emoji       TEXT    DEFAULT '💜',
    target_dates_per_month INTEGER DEFAULT 2,
    created_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS partner_dates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    partner_id  INTEGER NOT NULL REFERENCES partners(id),
    chat_id     INTEGER NOT NULL REFERENCES users(chat_id),
    date_type   TEXT    NOT NULL,               -- birthday | anniversary | date_night | custom
    label       TEXT,
    date_value  TEXT    NOT NULL,               -- ISO date or MM-DD for recurring
    recurring   INTEGER DEFAULT 1,
    notes       TEXT,
    created_at  TEXT    DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- MEDICATIONS
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS medications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL REFERENCES users(chat_id),
    name            TEXT    NOT NULL,
    dosage          TEXT,
    frequency       TEXT    DEFAULT 'daily',
    taken_today     INTEGER DEFAULT 0,
    refill_date     TEXT,
    notes           TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- NOTES (attachable to anything via 📒)
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL REFERENCES users(chat_id),
    category    TEXT,                           -- general | bill | car | partner | cred | med
    ref_id      INTEGER,                       -- FK to relevant table if attached
    content     TEXT    NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- APPOINTMENTS / EVENTS
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS appointments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL REFERENCES users(chat_id),
    title       TEXT    NOT NULL,
    event_date  TEXT    NOT NULL,               -- ISO date (YYYY-MM-DD)
    event_time  TEXT,                           -- HH:MM or NULL
    done        INTEGER DEFAULT 0,
    notes       TEXT,
    created_at  TEXT    DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- REMINDER LOG (nag tracking)
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS reminder_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    category    TEXT    NOT NULL,
    ref_id      INTEGER NOT NULL,
    sent_at     TEXT    DEFAULT (datetime('now')),
    nag_count   INTEGER DEFAULT 1
);

-- ═══════════════════════════════════════════════════════
-- SHIFT OVERRIDES (single-day exceptions)
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS shift_overrides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL REFERENCES users(chat_id),
    override_date TEXT NOT NULL,                -- ISO date
    is_working  INTEGER NOT NULL,               -- 1 = working, 0 = off
    notes       TEXT,
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(chat_id, override_date)
);

-- ═══════════════════════════════════════════════════════
-- KEY-VALUE SETTINGS (per user)
-- ═══════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER NOT NULL,
    key     TEXT    NOT NULL,
    value   TEXT,
    PRIMARY KEY (chat_id, key)
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


from contextlib import contextmanager

@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist."""
    with db() as conn:
        conn.executescript(SCHEMA)
    print("[DB] Tables initialized")


def ensure_user(chat_id: int, name: str = None):
    """Create user row if not exists. Return onboarded status."""
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (chat_id, display_name) VALUES (?, ?)",
                (chat_id, name or "Friend"),
            )
            return False  # not onboarded
        return bool(row["onboarded"])


def get_user(chat_id: int):
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()


def update_user(chat_id: int, **fields):
    with db() as conn:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [chat_id]
        conn.execute(f"UPDATE users SET {sets} WHERE chat_id = ?", vals)


if __name__ == "__main__":
    init_db()
    print("[DB] Ready")
