-- Proposal only. Run manually as the Neon owner after creating LOGIN role bot_state_writer.
GRANT CONNECT ON DATABASE neondb TO bot_state_writer;
GRANT USAGE ON SCHEMA bot_state TO bot_state_writer;

GRANT SELECT (max_user_id, subscription_status, subscription_expires_at, plate_last_digit, created_at, updated_at)
  ON bot_state.users TO bot_state_writer;
GRANT INSERT (max_user_id) ON bot_state.users TO bot_state_writer;
GRANT UPDATE (plate_last_digit, updated_at) ON bot_state.users TO bot_state_writer;

GRANT SELECT, INSERT, UPDATE, DELETE ON bot_state.plate_input_states TO bot_state_writer;
GRANT SELECT, INSERT, UPDATE ON bot_state.user_rate_limits TO bot_state_writer;
GRANT SELECT, INSERT, UPDATE ON bot_state.callback_receipts TO bot_state_writer;

-- No grants on public.fuel_facts, public.processed_source_messages, legacy tables, or schema CREATE.
-- Future manual subscription admin: grant UPDATE (subscription_status, subscription_expires_at) ON bot_state.users.
