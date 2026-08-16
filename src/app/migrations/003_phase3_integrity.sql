BEGIN IMMEDIATE;

CREATE TRIGGER IF NOT EXISTS trg_lookups_integrity_insert
BEFORE INSERT ON lookups
WHEN
    (NEW.status = 'SUCCESS' AND (
        NEW.vehicle_type IS NULL OR trim(NEW.vehicle_type) = '' OR
        NEW.brand IS NULL OR trim(NEW.brand) = '' OR
        NEW.inspection_expiry IS NULL OR NEW.finished_at IS NULL OR
        NEW.error_code IS NOT NULL
    )) OR
    (NEW.status <> 'SUCCESS' AND (
        NEW.vehicle_type IS NOT NULL OR NEW.brand IS NOT NULL OR
        NEW.inspection_expiry IS NOT NULL
    )) OR
    (NEW.status IN ('QUEUED', 'RUNNING') AND NEW.finished_at IS NOT NULL) OR
    (NEW.status IN ('INVALID', 'NOT_FOUND', 'ERROR') AND NEW.finished_at IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'invalid lookup state');
END;

CREATE TRIGGER IF NOT EXISTS trg_lookups_integrity_update
BEFORE UPDATE ON lookups
WHEN
    (NEW.status = 'SUCCESS' AND (
        NEW.vehicle_type IS NULL OR trim(NEW.vehicle_type) = '' OR
        NEW.brand IS NULL OR trim(NEW.brand) = '' OR
        NEW.inspection_expiry IS NULL OR NEW.finished_at IS NULL OR
        NEW.error_code IS NOT NULL
    )) OR
    (NEW.status <> 'SUCCESS' AND (
        NEW.vehicle_type IS NOT NULL OR NEW.brand IS NOT NULL OR
        NEW.inspection_expiry IS NOT NULL
    )) OR
    (NEW.status IN ('QUEUED', 'RUNNING') AND NEW.finished_at IS NOT NULL) OR
    (NEW.status IN ('INVALID', 'NOT_FOUND', 'ERROR') AND NEW.finished_at IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'invalid lookup state');
END;

CREATE TRIGGER IF NOT EXISTS trg_telegram_updates_integrity_insert
BEFORE INSERT ON telegram_updates
WHEN
    (NEW.state = 'ACCEPTED' AND NEW.finished_at IS NOT NULL) OR
    (NEW.state IN ('COMPLETED', 'FAILED') AND NEW.finished_at IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'invalid telegram update state');
END;

CREATE TRIGGER IF NOT EXISTS trg_telegram_updates_integrity_update
BEFORE UPDATE ON telegram_updates
WHEN
    (NEW.state = 'ACCEPTED' AND NEW.finished_at IS NOT NULL) OR
    (NEW.state IN ('COMPLETED', 'FAILED') AND NEW.finished_at IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'invalid telegram update state');
END;

PRAGMA user_version = 3;
COMMIT;
