-- Proposal only. Run manually as the Neon owner after all migration 003 phases.
-- Create LOGIN roles bot_state_writer and bot_admin_writer (NOINHERIT and without
-- broad memberships) and their passwords outside source control before this file.

-- No new PUBLIC access. Revoke defaults explicitly, including the sequence and
-- trigger function created by migration 003.
REVOKE ALL PRIVILEGES ON SCHEMA bot_state FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA bot_state FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA bot_state FROM PUBLIC;
REVOKE ALL PRIVILEGES ON FUNCTION bot_state.set_users_updated_at() FROM PUBLIC;

REVOKE ALL PRIVILEGES ON SCHEMA bot_state FROM bot_admin_writer;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA bot_state FROM bot_admin_writer;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA bot_state FROM bot_admin_writer;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM bot_admin_writer;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM bot_admin_writer;
GRANT CONNECT ON DATABASE neondb TO bot_admin_writer;
GRANT USAGE ON SCHEMA bot_state TO bot_admin_writer;

GRANT SELECT (id, max_user_id, subscription_status, subscription_expires_at, plate_last_digit,
              created_at, updated_at, first_seen_at, last_seen_at, total_accepted_fuel_lookups)
  ON bot_state.users TO bot_admin_writer;
-- admin-users.js reads only these rate-limit, pending-plate, and callback fields.
GRANT SELECT (max_user_id, last_lookup_at, recent_lookup_at, daily_service_date, daily_lookup_count)
  ON bot_state.user_rate_limits TO bot_admin_writer;
GRANT SELECT (max_user_id, state, expires_at)
  ON bot_state.plate_input_states TO bot_admin_writer;
GRANT SELECT (max_user_id, status)
  ON bot_state.callback_receipts TO bot_admin_writer;
GRANT UPDATE (subscription_status, subscription_expires_at, plate_last_digit)
  ON bot_state.users TO bot_admin_writer;
GRANT UPDATE (last_lookup_at, recent_lookup_at, daily_service_date, daily_lookup_count)
  ON bot_state.user_rate_limits TO bot_admin_writer;

-- bot_admin_writer never inserts into users and receives no sequence or function
-- EXECUTE privilege. Replace broad runtime grants with exactly the current SQL.
REVOKE ALL PRIVILEGES ON bot_state.users FROM bot_state_writer;
REVOKE ALL PRIVILEGES ON bot_state.plate_input_states FROM bot_state_writer;
REVOKE ALL PRIVILEGES ON bot_state.user_rate_limits FROM bot_state_writer;
REVOKE ALL PRIVILEGES ON bot_state.callback_receipts FROM bot_state_writer;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA bot_state FROM bot_state_writer;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM bot_state_writer;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM bot_state_writer;
GRANT CONNECT ON DATABASE neondb TO bot_state_writer;
GRANT USAGE ON SCHEMA bot_state TO bot_state_writer;

GRANT SELECT (max_user_id, subscription_status, subscription_expires_at, plate_last_digit,
              last_seen_at, total_accepted_fuel_lookups)
  ON bot_state.users TO bot_state_writer;
GRANT INSERT (max_user_id) ON bot_state.users TO bot_state_writer;
-- Keep updated_at through the bot deployment transition. Remove it only in a
-- later cleanup after the deployed runtime is verified not to set it directly.
GRANT UPDATE (plate_last_digit, last_seen_at, total_accepted_fuel_lookups, updated_at)
  ON bot_state.users TO bot_state_writer;

DO $$
BEGIN
  IF pg_get_serial_sequence('bot_state.users', 'id') <> 'bot_state.users_id_seq' THEN
    RAISE EXCEPTION 'unexpected users.id sequence: %',
      pg_get_serial_sequence('bot_state.users', 'id');
  END IF;
END;
$$;
GRANT USAGE ON SEQUENCE bot_state.users_id_seq TO bot_state_writer;

GRANT SELECT (max_user_id, state, expires_at)
  ON bot_state.plate_input_states TO bot_state_writer;
GRANT INSERT (max_user_id, state, expires_at)
  ON bot_state.plate_input_states TO bot_state_writer;
GRANT UPDATE (state, expires_at) ON bot_state.plate_input_states TO bot_state_writer;
GRANT DELETE ON bot_state.plate_input_states TO bot_state_writer;

GRANT SELECT (max_user_id, last_lookup_at, recent_lookup_at, daily_service_date, daily_lookup_count)
  ON bot_state.user_rate_limits TO bot_state_writer;
GRANT INSERT (max_user_id, daily_service_date) ON bot_state.user_rate_limits TO bot_state_writer;
GRANT UPDATE (last_lookup_at, recent_lookup_at, daily_service_date, daily_lookup_count, updated_at)
  ON bot_state.user_rate_limits TO bot_state_writer;

GRANT SELECT (max_user_id, callback_id, status, lease_expires_at)
  ON bot_state.callback_receipts TO bot_state_writer;
GRANT INSERT (max_user_id, callback_id, status, lease_expires_at)
  ON bot_state.callback_receipts TO bot_state_writer;
GRANT UPDATE (status, lease_expires_at, completed_at)
  ON bot_state.callback_receipts TO bot_state_writer;

-- No grants on public.fuel_facts, public.processed_source_messages, CREATE,
-- role/grant management, DDL, DELETE users, or INSERT/DELETE/TRUNCATE users.
