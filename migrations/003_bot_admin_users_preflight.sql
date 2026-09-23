-- Read-only preflight for the Neon owner. Review results before migration 003.
SELECT current_user, current_database();

SELECT c.oid::regclass AS relation, r.rolname AS owner,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
       c.reltuples::bigint AS estimated_rows
FROM pg_class AS c
JOIN pg_roles AS r ON r.oid = c.relowner
WHERE c.oid IN ('bot_state.users'::regclass, 'bot_state.callback_receipts'::regclass);

SELECT conname, contype, convalidated, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'bot_state.users'::regclass
ORDER BY conname;

SELECT c.oid::regclass AS relation, i.relname AS index_name, x.indisvalid, x.indisready
FROM pg_index AS x
JOIN pg_class AS c ON c.oid = x.indrelid
JOIN pg_class AS i ON i.oid = x.indexrelid
WHERE x.indrelid IN ('bot_state.users'::regclass, 'bot_state.callback_receipts'::regclass)
ORDER BY relation, index_name;

SELECT CASE
  WHEN EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'bot_state' AND table_name = 'users' AND column_name = 'id'
  ) THEN pg_get_serial_sequence('bot_state.users', 'id')
END AS existing_id_sequence;

SELECT member.rolname AS member_role, parent.rolname AS granted_role
FROM pg_auth_members AS membership
JOIN pg_roles AS member ON member.oid = membership.member
JOIN pg_roles AS parent ON parent.oid = membership.roleid
WHERE member.rolname IN ('bot_state_writer', 'bot_admin_writer')
ORDER BY member_role, granted_role;

SELECT grantee, table_schema, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema IN ('bot_state', 'public')
  AND grantee IN ('PUBLIC', 'bot_state_writer', 'bot_admin_writer')
ORDER BY grantee, table_schema, table_name, privilege_type;
