-- Proposal only. Run manually as the Neon owner after migration 004 succeeds.
-- This is additive to the hardened 003 grants; do not grant any privileges to PUBLIC.

REVOKE ALL PRIVILEGES ON bot_state.user_vehicles FROM PUBLIC;
REVOKE ALL PRIVILEGES ON SEQUENCE bot_state.user_vehicles_id_seq FROM PUBLIC;
REVOKE ALL PRIVILEGES ON FUNCTION bot_state.enforce_user_vehicle_limit() FROM PUBLIC;
REVOKE ALL PRIVILEGES ON FUNCTION bot_state.set_user_vehicle_updated_at() FROM PUBLIC;

REVOKE ALL PRIVILEGES ON bot_state.user_vehicles FROM bot_admin_writer;
REVOKE ALL PRIVILEGES ON SEQUENCE bot_state.user_vehicles_id_seq FROM bot_admin_writer;
GRANT SELECT (display_name, free_lookup_used_at) ON bot_state.users TO bot_admin_writer;
GRANT UPDATE (free_lookup_used_at) ON bot_state.users TO bot_admin_writer;
GRANT SELECT (id, max_user_id, plate_normalized, plate_last_digit, created_at, updated_at)
  ON bot_state.user_vehicles TO bot_admin_writer;

REVOKE ALL PRIVILEGES ON bot_state.user_vehicles FROM bot_state_writer;
REVOKE ALL PRIVILEGES ON SEQUENCE bot_state.user_vehicles_id_seq FROM bot_state_writer;
GRANT SELECT (display_name, free_lookup_used_at) ON bot_state.users TO bot_state_writer;
GRANT UPDATE (display_name, free_lookup_used_at) ON bot_state.users TO bot_state_writer;
GRANT SELECT (id, max_user_id, plate_normalized, plate_last_digit, created_at, updated_at)
  ON bot_state.user_vehicles TO bot_state_writer;
GRANT INSERT (max_user_id, plate_normalized, plate_last_digit) ON bot_state.user_vehicles TO bot_state_writer;
GRANT UPDATE (plate_normalized, plate_last_digit) ON bot_state.user_vehicles TO bot_state_writer;
GRANT DELETE ON bot_state.user_vehicles TO bot_state_writer;
GRANT USAGE ON SEQUENCE bot_state.user_vehicles_id_seq TO bot_state_writer;

-- No grants change for bot_facts_reader or collector_writer. No INSERT/UPDATE/
-- DELETE vehicles grants for bot_admin_writer; no grants on public source tables.
