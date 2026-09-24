-- Read-only post-migration and grants audit.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'bot_state' AND table_name = 'users'
  AND column_name IN ('display_name', 'free_lookup_used_at')
ORDER BY column_name;

SELECT conname, contype, convalidated, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'bot_state.user_vehicles'::regclass
ORDER BY conname;

SELECT trigger_name, event_manipulation, action_timing, action_statement
FROM information_schema.triggers
WHERE event_object_schema = 'bot_state' AND event_object_table = 'user_vehicles'
ORDER BY trigger_name;

SELECT role_name,
       has_table_privilege(role_name, 'bot_state.user_vehicles', 'SELECT') AS vehicles_select,
       has_table_privilege(role_name, 'bot_state.user_vehicles', 'INSERT') AS vehicles_insert,
       has_table_privilege(role_name, 'bot_state.user_vehicles', 'UPDATE') AS vehicles_update,
       has_table_privilege(role_name, 'bot_state.user_vehicles', 'DELETE') AS vehicles_delete,
       has_sequence_privilege(role_name, 'bot_state.user_vehicles_id_seq', 'USAGE') AS vehicles_sequence_usage,
       has_table_privilege(role_name, 'public.fuel_facts', 'SELECT') AS fuel_facts_select,
       has_table_privilege(role_name, 'public.processed_source_messages', 'SELECT') AS source_messages_select
FROM (VALUES ('PUBLIC'::name), ('bot_state_writer'::name), ('bot_admin_writer'::name), ('bot_facts_reader'::name), ('collector_writer'::name)) AS roles(role_name);

SELECT role_name, column_name,
       has_column_privilege(role_name, 'bot_state.users', column_name, 'SELECT') AS can_select,
       has_column_privilege(role_name, 'bot_state.users', column_name, 'UPDATE') AS can_update
FROM (VALUES
  ('bot_state_writer'::name, 'display_name'::text),
  ('bot_state_writer'::name, 'free_lookup_used_at'::text),
  ('bot_admin_writer'::name, 'display_name'::text),
  ('bot_admin_writer'::name, 'free_lookup_used_at'::text)
) AS requested(role_name, column_name)
ORDER BY role_name, column_name;
