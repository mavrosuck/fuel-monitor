-- Read-only audit after migration 003 and grants. Invalid indexes must be removed
-- individually with DROP INDEX CONCURRENTLY before rerunning phase 2.
SELECT c.oid::regclass AS relation, i.relname AS index_name, x.indisvalid, x.indisready
FROM pg_index AS x
JOIN pg_class AS c ON c.oid = x.indrelid
JOIN pg_class AS i ON i.oid = x.indexrelid
WHERE i.relname IN ('users_id_unique_idx', 'users_admin_status_id_idx', 'callback_receipts_admin_summary_idx')
ORDER BY index_name;

SELECT pg_get_serial_sequence('bot_state.users', 'id') AS id_sequence,
       has_sequence_privilege('bot_state_writer', 'bot_state.users_id_seq', 'USAGE') AS writer_sequence_usage,
       has_sequence_privilege('bot_admin_writer', 'bot_state.users_id_seq', 'USAGE') AS admin_sequence_usage;

SELECT role_name,
       has_database_privilege(role_name, current_database(), 'CONNECT') AS database_connect,
       has_schema_privilege(role_name, 'bot_state', 'USAGE') AS schema_usage,
       has_schema_privilege(role_name, 'public', 'CREATE') AS public_schema_create,
       has_function_privilege(role_name, 'bot_state.set_users_updated_at()', 'EXECUTE') AS trigger_function_execute,
       has_table_privilege(role_name, 'bot_state.users', 'DELETE') AS users_delete,
       has_table_privilege(role_name, 'bot_state.users', 'TRUNCATE') AS users_truncate,
       has_column_privilege(role_name, 'bot_state.users', 'max_user_id', 'INSERT') AS users_insert_max_user_id
FROM (VALUES ('bot_state_writer'::name), ('bot_admin_writer'::name), ('PUBLIC'::name)) AS roles(role_name);

SELECT role_name, relation_name, column_name,
       has_column_privilege(role_name, relation_name, column_name, 'SELECT') AS can_select,
       has_column_privilege(role_name, relation_name, column_name, 'UPDATE') AS can_update
FROM (VALUES
  ('bot_state_writer'::name, 'bot_state.users'::text, 'last_seen_at'::text),
  ('bot_state_writer'::name, 'bot_state.users'::text, 'total_accepted_fuel_lookups'::text),
  ('bot_state_writer'::name, 'bot_state.users'::text, 'updated_at'::text),
  ('bot_admin_writer'::name, 'bot_state.users'::text, 'subscription_status'::text),
  ('bot_admin_writer'::name, 'bot_state.users'::text, 'updated_at'::text),
  ('bot_admin_writer'::name, 'bot_state.users'::text, 'id'::text),
  ('bot_admin_writer'::name, 'bot_state.user_rate_limits'::text, 'max_user_id'::text),
  ('bot_admin_writer'::name, 'bot_state.user_rate_limits'::text, 'last_lookup_at'::text),
  ('bot_admin_writer'::name, 'bot_state.user_rate_limits'::text, 'recent_lookup_at'::text),
  ('bot_admin_writer'::name, 'bot_state.user_rate_limits'::text, 'daily_service_date'::text),
  ('bot_admin_writer'::name, 'bot_state.user_rate_limits'::text, 'daily_lookup_count'::text),
  ('bot_admin_writer'::name, 'bot_state.plate_input_states'::text, 'max_user_id'::text),
  ('bot_admin_writer'::name, 'bot_state.plate_input_states'::text, 'state'::text),
  ('bot_admin_writer'::name, 'bot_state.plate_input_states'::text, 'expires_at'::text),
  ('bot_admin_writer'::name, 'bot_state.callback_receipts'::text, 'max_user_id'::text),
  ('bot_admin_writer'::name, 'bot_state.callback_receipts'::text, 'status'::text)
) AS requested(role_name, relation_name, column_name)
ORDER BY role_name, relation_name, column_name;

SELECT grantee, table_schema, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public'
  AND grantee IN ('bot_state_writer', 'bot_admin_writer', 'PUBLIC')
ORDER BY grantee, table_name, privilege_type;
