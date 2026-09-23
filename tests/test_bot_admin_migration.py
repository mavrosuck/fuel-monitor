from pathlib import Path


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def test_admin_user_migration_keeps_max_user_id_primary_key_and_adds_unique_identity() -> None:
    base_schema = (MIGRATIONS / "002_bot_state.sql").read_text()
    migration = (MIGRATIONS / "003_bot_admin_users.sql").read_text()

    assert "max_user_id TEXT PRIMARY KEY" in base_schema
    assert "ADD COLUMN IF NOT EXISTS id BIGINT" in migration
    assert "CREATE SEQUENCE IF NOT EXISTS bot_state.users_id_seq AS BIGINT" in migration
    assert "ALTER SEQUENCE bot_state.users_id_seq OWNED BY bot_state.users.id" in migration
    assert "LOCK TABLE bot_state.users IN SHARE ROW EXCLUSIVE MODE" in migration
    assert "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS users_id_unique_idx" in migration
    assert "duplicate bot_state.users.id values require manual recovery" in migration
    assert "DROP INDEX CONCURRENTLY IF EXISTS bot_state.callback_receipts_admin_summary_idx" in migration
    assert "CREATE INDEX CONCURRENTLY callback_receipts_admin_summary_idx" not in migration
    assert "ALTER COLUMN max_user_id" not in migration
    assert "REFERENCES bot_state.users(max_user_id)" in base_schema


def test_admin_grants_are_column_scoped_and_do_not_grant_the_identity_sequence() -> None:
    grants = (MIGRATIONS / "003_bot_admin_users_grants_proposal.sql").read_text()

    admin_section, runtime_section = grants.split("-- bot_admin_writer never inserts", maxsplit=1)
    assert "GRANT UPDATE (subscription_status, subscription_expires_at, plate_last_digit)" in admin_section
    assert "GRANT UPDATE (last_lookup_at, recent_lookup_at, daily_service_date, daily_lookup_count)" in admin_section
    assert "GRANT SELECT (max_user_id, last_lookup_at, recent_lookup_at, daily_service_date, daily_lookup_count)\n  ON bot_state.user_rate_limits TO bot_admin_writer" in admin_section
    assert "GRANT SELECT (max_user_id, state, expires_at)\n  ON bot_state.plate_input_states TO bot_admin_writer" in admin_section
    assert "GRANT SELECT (max_user_id, status)\n  ON bot_state.callback_receipts TO bot_admin_writer" in admin_section
    assert "ON SEQUENCE bot_state.users_id_seq TO bot_admin_writer" not in grants
    assert "GRANT UPDATE (last_lookup_at, recent_lookup_at, daily_service_date, daily_lookup_count, updated_at)\n  ON bot_state.user_rate_limits TO bot_admin_writer" not in grants
    assert "public.fuel_facts" not in admin_section
    assert "public.processed_source_messages" not in admin_section
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM bot_state_writer" in runtime_section
    assert "last_seen_at, total_accepted_fuel_lookups" in runtime_section
    assert "total_accepted_fuel_lookups, updated_at" in runtime_section
    assert "GRANT USAGE ON SEQUENCE bot_state.users_id_seq TO bot_state_writer" in runtime_section


def test_trigger_is_invoker_hardened_and_public_receives_no_execute() -> None:
    migration = (MIGRATIONS / "003_bot_admin_users.sql").read_text()
    grants = (MIGRATIONS / "003_bot_admin_users_grants_proposal.sql").read_text()

    assert "SECURITY INVOKER" in migration
    assert "SET search_path = pg_catalog" in migration
    assert "REVOKE ALL PRIVILEGES ON FUNCTION bot_state.set_users_updated_at() FROM PUBLIC" in migration
    assert "GRANT EXECUTE ON FUNCTION bot_state.set_users_updated_at" not in grants


def test_preflight_audit_and_functional_permission_scripts_are_present() -> None:
    preflight = (MIGRATIONS / "003_bot_admin_users_preflight.sql").read_text()
    audit = (MIGRATIONS / "003_bot_admin_users_audit.sql").read_text()
    functional = (MIGRATIONS / "003_bot_admin_users_functional_permission_test.sql").read_text()

    assert "pg_total_relation_size" in preflight
    assert "pg_auth_members" in preflight
    assert "indisvalid" in audit
    assert "has_column_privilege" in audit
    assert "bot_state.user_rate_limits" in audit
    assert "bot_state.plate_input_states" in audit
    assert "bot_state.callback_receipts" in audit
    assert "SELECT max_user_id, last_lookup_at, recent_lookup_at, daily_service_date, daily_lookup_count" in functional
    assert "SELECT max_user_id, state, expires_at" in functional
    assert "SELECT max_user_id, status" in functional
    assert functional.count("ROLLBACK;") == 2
