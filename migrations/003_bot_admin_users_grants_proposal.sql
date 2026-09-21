-- Proposal only. Run manually as the Neon owner after migration 003_bot_admin_users.sql.
-- Create LOGIN role bot_admin_writer and its password outside source control.
-- Verify bot_admin_writer has no inherited membership in broad roles before applying.

REVOKE ALL PRIVILEGES ON SCHEMA bot_state FROM bot_admin_writer;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA bot_state FROM bot_admin_writer;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA bot_state FROM bot_admin_writer;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM bot_admin_writer;
GRANT CONNECT ON DATABASE neondb TO bot_admin_writer;
GRANT USAGE ON SCHEMA bot_state TO bot_admin_writer;

GRANT SELECT (id, max_user_id, subscription_status, subscription_expires_at, plate_last_digit,
              created_at, updated_at, first_seen_at, last_seen_at, total_accepted_fuel_lookups)
  ON bot_state.users TO bot_admin_writer;
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

-- bot_admin_writer never inserts into bot_state.users, so it receives no identity-sequence grant.
-- Replace broad runtime table grants with the exact columns used by fuel-max-bot.
-- Verify with SELECT pg_get_serial_sequence('bot_state.users', 'id'); before granting sequence usage.
REVOKE ALL PRIVILEGES ON bot_state.users FROM bot_state_writer;
REVOKE ALL PRIVILEGES ON bot_state.plate_input_states FROM bot_state_writer;
REVOKE ALL PRIVILEGES ON bot_state.user_rate_limits FROM bot_state_writer;
REVOKE ALL PRIVILEGES ON bot_state.callback_receipts FROM bot_state_writer;
GRANT USAGE ON SCHEMA bot_state TO bot_state_writer;
GRANT SELECT (max_user_id, subscription_status, subscription_expires_at, plate_last_digit)
  ON bot_state.users TO bot_state_writer;
GRANT INSERT (max_user_id) ON bot_state.users TO bot_state_writer;
GRANT UPDATE (plate_last_digit, last_seen_at, total_accepted_fuel_lookups)
  ON bot_state.users TO bot_state_writer;
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

-- No grants on public.fuel_facts, public.processed_source_messages, schemas, role management, or DDL.
