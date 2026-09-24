-- Shared Neon schema authority: fuel-monitor.
-- Apply manually as the database owner after every migration/003_* phase.
-- Run migrations/004_user_profiles_and_vehicles_preflight.sql first.
-- This migration is additive: it does not alter bot_state.users(max_user_id), its
-- primary key, or foreign keys that reference it.

BEGIN;

ALTER TABLE bot_state.users
  ADD COLUMN IF NOT EXISTS display_name TEXT,
  ADD COLUMN IF NOT EXISTS free_lookup_used_at TIMESTAMPTZ;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'bot_state' AND table_name = 'users'
      AND column_name = 'display_name' AND data_type <> 'text'
  ) THEN
    RAISE EXCEPTION 'bot_state.users.display_name must be text';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'bot_state' AND table_name = 'users'
      AND column_name = 'free_lookup_used_at' AND data_type <> 'timestamp with time zone'
  ) THEN
    RAISE EXCEPTION 'bot_state.users.free_lookup_used_at must be timestamptz';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'bot_state.users'::regclass AND conname = 'users_display_name_length'
  ) THEN
    ALTER TABLE bot_state.users
      ADD CONSTRAINT users_display_name_length
      CHECK (display_name IS NULL OR char_length(display_name) BETWEEN 1 AND 200) NOT VALID;
  END IF;
END;
$$;
ALTER TABLE bot_state.users VALIDATE CONSTRAINT users_display_name_length;

CREATE SEQUENCE IF NOT EXISTS bot_state.user_vehicles_id_seq AS BIGINT;
CREATE TABLE IF NOT EXISTS bot_state.user_vehicles (
  id BIGINT NOT NULL DEFAULT nextval('bot_state.user_vehicles_id_seq'::regclass),
  max_user_id TEXT NOT NULL REFERENCES bot_state.users(max_user_id),
  plate_normalized TEXT NOT NULL,
  plate_last_digit SMALLINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT user_vehicles_pkey PRIMARY KEY (id),
  CONSTRAINT user_vehicles_plate_last_digit CHECK (plate_last_digit BETWEEN 0 AND 9),
  CONSTRAINT user_vehicles_plate_normalized_format CHECK (
    plate_normalized ~ '^[АВЕКМНОРСТУХ][0-9]{3}[АВЕКМНОРСТУХ]{2}[0-9]{2,3}$'
  ),
  CONSTRAINT user_vehicles_user_plate_unique UNIQUE (max_user_id, plate_normalized)
);
ALTER SEQUENCE bot_state.user_vehicles_id_seq OWNED BY bot_state.user_vehicles.id;

SELECT setval(
  'bot_state.user_vehicles_id_seq'::regclass,
  COALESCE((SELECT max(id) FROM bot_state.user_vehicles), 1),
  EXISTS (SELECT 1 FROM bot_state.user_vehicles)
);

CREATE OR REPLACE FUNCTION bot_state.enforce_user_vehicle_limit()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $$
DECLARE
  vehicle_count INTEGER;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.max_user_id, 415332));
  SELECT count(*) INTO vehicle_count
  FROM bot_state.user_vehicles
  WHERE max_user_id = NEW.max_user_id;
  IF vehicle_count >= 3 THEN
    RAISE EXCEPTION 'user vehicle limit reached' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION bot_state.set_user_vehicle_updated_at()
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

REVOKE ALL PRIVILEGES ON FUNCTION bot_state.enforce_user_vehicle_limit() FROM PUBLIC;
REVOKE ALL PRIVILEGES ON FUNCTION bot_state.set_user_vehicle_updated_at() FROM PUBLIC;
DROP TRIGGER IF EXISTS user_vehicles_limit_before_insert ON bot_state.user_vehicles;
CREATE TRIGGER user_vehicles_limit_before_insert
  BEFORE INSERT ON bot_state.user_vehicles
  FOR EACH ROW
  EXECUTE FUNCTION bot_state.enforce_user_vehicle_limit();
DROP TRIGGER IF EXISTS user_vehicles_set_updated_at ON bot_state.user_vehicles;
CREATE TRIGGER user_vehicles_set_updated_at
  BEFORE UPDATE ON bot_state.user_vehicles
  FOR EACH ROW
  EXECUTE FUNCTION bot_state.set_user_vehicle_updated_at();

COMMIT;

-- user_vehicles_user_plate_unique starts with max_user_id and serves list-by-user;
-- a separate max_user_id index would be redundant. No display-name index is added
-- until production data justifies it with EXPLAIN for local-admin searches.
