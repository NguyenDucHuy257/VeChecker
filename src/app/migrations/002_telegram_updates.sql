BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS telegram_updates (
    update_id INTEGER PRIMARY KEY,
    telegram_user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('ACCEPTED', 'COMPLETED', 'FAILED')),
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_telegram_updates_state
    ON telegram_updates(state);

PRAGMA user_version = 2;
COMMIT;
