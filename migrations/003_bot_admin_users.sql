-- Shared Neon schema authority: fuel-monitor.
-- Apply manually as the database owner after migrations/001_* and migrations/002_*.
-- Run migrations/003_bot_admin_users_preflight.sql first. Do not wrap this whole
-- file in a transaction: phase 2 deliberately uses CREATE INDEX CONCURRENTLY.
-- max_user_id remains the primary key; all existing foreign keys remain unchanged.

-- PHASE 1 — schema, backfill, and validation. This is one short write-maintenance
-- transaction: SHARE ROW EXCLUSIVE permits reads but blocks concurrent writes to
-- users while existing rows receive stable internal ids and the sequence is aligned.
BEGIN;

DO $$
BEGIN
  IF (SELECT relowner FROM pg_class WHERE oid = 'bot_state.users'::regclass)
       <> (SELECT oid FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'current_user must own bot_state.users';
  END IF;
END;
$$;

LOCK TABLE bot_state.users IN SHARE ROW EXCLUSIVE MODE;

ALTER TABLE bot_state.users
  ADD COLUMN IF NOT EXISTS id BIGINT,
  ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS total_accepted_fuel_lookups BIGINT;

-- The name is fixed here and owned by users.id, so pg_get_serial_sequence can
-- later verify it before the runtime role receives the minimal USAGE privilege.
CREATE SEQUENCE IF NOT EXISTS bot_state.users_id_seq AS BIGINT;
ALTER SEQUENCE bot_state.users_id_seq OWNED BY bot_state.users.id;
ALTER TABLE bot_state.users
  ALTER COLUMN id SET DEFAULT nextval('bot_state.users_id_seq'::regclass),
  ALTER COLUMN first_seen_at SET DEFAULT clock_timestamp(),
  ALTER COLUMN last_seen_at SET DEFAULT clock_timestamp(),
  ALTER COLUMN total_accepted_fuel_lookups SET DEFAULT 0;

UPDATE bot_state.users
SET id = COALESCE(id, nextval('bot_state.users_id_seq'::regclass)),
    first_seen_at = COALESCE(first_seen_at, created_at, clock_timestamp()),
    last_seen_at = COALESCE(last_seen_at, updated_at, created_at, clock_timestamp()),
    total_accepted_fuel_lookups = COALESCE(total_accepted_fuel_lookups, 0)
WHERE id IS NULL
   OR first_seen_at IS NULL
   OR last_seen_at IS NULL
   OR total_accepted_fuel_lookups IS NULL;

SELECT setval(
  'bot_state.users_id_seq'::regclass,
  COALESCE((SELECT max(id) FROM bot_state.users), 1),
  EXISTS (SELECT 1 FROM bot_state.users)
);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM bot_state.users
    WHERE id IS NOT NULL
    GROUP BY id
    HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION 'duplicate bot_state.users.id values require manual recovery before phase 2';
  END IF;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'bot_state.users'::regclass AND conname = 'users_id_present'
  ) THEN
    ALTER TABLE bot_state.users
      ADD CONSTRAINT users_id_present CHECK (id IS NOT NULL) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'bot_state.users'::regclass AND conname = 'users_first_seen_at_present'
  ) THEN
    ALTER TABLE bot_state.users
      ADD CONSTRAINT users_first_seen_at_present CHECK (first_seen_at IS NOT NULL) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'bot_state.users'::regclass AND conname = 'users_last_seen_at_present'
  ) THEN
    ALTER TABLE bot_state.users
      ADD CONSTRAINT users_last_seen_at_present CHECK (last_seen_at IS NOT NULL) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'bot_state.users'::regclass AND conname = 'users_total_accepted_fuel_lookups_present'
  ) THEN
    ALTER TABLE bot_state.users
      ADD CONSTRAINT users_total_accepted_fuel_lookups_present
      CHECK (total_accepted_fuel_lookups IS NOT NULL) NOT VALID;
  END IF;
END;
$$;

ALTER TABLE bot_state.users VALIDATE CONSTRAINT users_id_present;
ALTER TABLE bot_state.users VALIDATE CONSTRAINT users_first_seen_at_present;
ALTER TABLE bot_state.users VALIDATE CONSTRAINT users_last_seen_at_present;
ALTER TABLE bot_state.users VALIDATE CONSTRAINT users_total_accepted_fuel_lookups_present;

COMMIT;

-- PHASE 2 — run each statement outside a transaction. Before retrying this phase
-- after an interruption, run 003_bot_admin_users_audit.sql and drop only an
-- explicitly reported invalid index with DROP INDEX CONCURRENTLY, then rerun it.
DROP INDEX CONCURRENTLY IF EXISTS bot_state.callback_receipts_admin_summary_idx;
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS users_id_unique_idx
  ON bot_state.users (id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS users_admin_status_id_idx
  ON bot_state.users (subscription_status, id DESC);

-- PHASE 3 — trigger hardening. It is SECURITY INVOKER, resolves only pg_catalog,
-- and has no PUBLIC EXECUTE privilege. A BEFORE trigger changes NEW directly, so
-- it neither issues another UPDATE nor recursively invokes itself.
BEGIN;
CREATE OR REPLACE FUNCTION bot_state.set_users_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $$
BEGIN
  NEW.updated_at = clock_timestamp();
  RETURN NEW;
END;
$$;

REVOKE ALL PRIVILEGES ON FUNCTION bot_state.set_users_updated_at() FROM PUBLIC;
DROP TRIGGER IF EXISTS users_set_updated_at ON bot_state.users;
CREATE TRIGGER users_set_updated_at
  BEFORE UPDATE ON bot_state.users
  FOR EACH ROW
  EXECUTE FUNCTION bot_state.set_users_updated_at();
COMMIT;
