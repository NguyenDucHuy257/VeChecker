BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL UNIQUE,
    telegram_username TEXT,
    role TEXT NOT NULL CHECK (role IN ('ADMIN', 'USER')),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'ACTIVE', 'BLOCKED')),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS lookups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    input_plate TEXT NOT NULL,
    queried_plate TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('QUEUED', 'RUNNING', 'SUCCESS', 'INVALID', 'NOT_FOUND', 'ERROR')
    ),
    vehicle_type TEXT,
    brand TEXT,
    inspection_expiry TEXT,
    error_code TEXT,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_lookups_user_created
    ON lookups(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_lookups_status
    ON lookups(status);

PRAGMA user_version = 1;
COMMIT;
