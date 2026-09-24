-- Read-only preflight. Review all results before migration 004.
SELECT current_user, current_database();

SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'bot_state' AND table_name = 'users'
  AND column_name IN ('max_user_id', 'display_name', 'free_lookup_used_at')
ORDER BY column_name;

SELECT to_regclass('bot_state.user_vehicles') AS user_vehicles_relation,
       to_regclass('bot_state.user_vehicles_id_seq') AS user_vehicles_sequence;

SELECT count(*) AS existing_users
FROM bot_state.users;

SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'bot_state.users'::regclass
ORDER BY conname;

SELECT grantee, table_schema, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE grantee IN ('PUBLIC', 'bot_state_writer', 'bot_admin_writer', 'bot_facts_reader', 'collector_writer')
  AND table_schema IN ('bot_state', 'public')
ORDER BY grantee, table_schema, table_name, privilege_type;
