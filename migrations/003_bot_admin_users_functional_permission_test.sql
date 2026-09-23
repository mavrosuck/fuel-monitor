-- Connect separately as each named role. Every test is rolled back.
-- bot_state_writer: proves default id generation, required read-modify-write
-- privileges, and trigger execution without direct EXECUTE on the function.
BEGIN;
INSERT INTO bot_state.users (max_user_id)
VALUES ((9000000000000000000 + txid_current())::text);
UPDATE bot_state.users
SET last_seen_at = clock_timestamp()
WHERE max_user_id = (9000000000000000000 + txid_current())::text
  AND last_seen_at < clock_timestamp() + INTERVAL '1 second';
UPDATE bot_state.users
SET total_accepted_fuel_lookups = total_accepted_fuel_lookups + 1
WHERE max_user_id = (9000000000000000000 + txid_current())::text;
SELECT has_function_privilege(current_user, 'bot_state.set_users_updated_at()', 'EXECUTE') AS direct_execute_must_be_false;
ROLLBACK;

-- bot_admin_writer: query and zero-row updates prove the narrow permissions
-- without changing production data. This role must not have direct function EXECUTE.
BEGIN;
SELECT id, max_user_id, subscription_status, last_seen_at, total_accepted_fuel_lookups
FROM bot_state.users ORDER BY id DESC LIMIT 1;
SELECT max_user_id, last_lookup_at, recent_lookup_at, daily_service_date, daily_lookup_count
FROM bot_state.user_rate_limits LIMIT 1;
SELECT max_user_id, state, expires_at
FROM bot_state.plate_input_states LIMIT 1;
SELECT max_user_id, status
FROM bot_state.callback_receipts LIMIT 1;
UPDATE bot_state.users SET subscription_status = subscription_status WHERE id = -1;
UPDATE bot_state.user_rate_limits SET daily_lookup_count = daily_lookup_count WHERE max_user_id = '__permission_test__';
SELECT has_function_privilege(current_user, 'bot_state.set_users_updated_at()', 'EXECUTE') AS direct_execute_must_be_false;
ROLLBACK;
