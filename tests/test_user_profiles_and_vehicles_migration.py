from pathlib import Path


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def test_user_profile_columns_are_additive_and_nullable() -> None:
    migration = (MIGRATIONS / "004_user_profiles_and_vehicles.sql").read_text()

    assert "ADD COLUMN IF NOT EXISTS display_name TEXT" in migration
    assert "ADD COLUMN IF NOT EXISTS free_lookup_used_at TIMESTAMPTZ" in migration
    assert "ALTER COLUMN max_user_id" not in migration
    assert "display_name IS NULL OR char_length(display_name) BETWEEN 1 AND 200" in migration


def test_vehicles_have_database_constraints_and_a_three_vehicle_guard() -> None:
    migration = (MIGRATIONS / "004_user_profiles_and_vehicles.sql").read_text()
    functional = (MIGRATIONS / "004_user_profiles_and_vehicles_functional_test.sql").read_text()

    assert "REFERENCES bot_state.users(max_user_id)" in migration
    assert "ON DELETE CASCADE" not in migration
    assert "plate_last_digit BETWEEN 0 AND 9" in migration
    assert "plate_normalized ~" in migration
    assert "user_vehicles_user_plate_unique UNIQUE (max_user_id, plate_normalized)" in migration
    assert "pg_advisory_xact_lock" in migration
    assert "vehicle_count >= 3" in migration
    assert "fourth vehicle was accepted" in functional
    assert "duplicate vehicle was accepted" in functional


def test_new_functions_and_grants_are_least_privilege() -> None:
    migration = (MIGRATIONS / "004_user_profiles_and_vehicles.sql").read_text()
    grants = (MIGRATIONS / "004_user_profiles_and_vehicles_grants_proposal.sql").read_text()

    assert migration.count("SECURITY INVOKER") == 2
    assert migration.count("SET search_path = pg_catalog") == 2
    assert "REVOKE ALL PRIVILEGES ON FUNCTION bot_state.enforce_user_vehicle_limit() FROM PUBLIC" in migration
    assert "GRANT UPDATE (free_lookup_used_at) ON bot_state.users TO bot_admin_writer" in grants
    assert "ON bot_state.user_vehicles TO bot_admin_writer" in grants
    assert "GRANT INSERT" not in grants.split("bot_state_writer", maxsplit=1)[0]
    assert "GRANT USAGE ON SEQUENCE bot_state.user_vehicles_id_seq TO bot_admin_writer" not in grants
    assert "GRANT USAGE ON SEQUENCE bot_state.user_vehicles_id_seq TO bot_state_writer" in grants
    assert "TO bot_facts_reader" not in grants
    assert "TO collector_writer" not in grants
    assert "TO PUBLIC" not in grants.replace("REVOKE ALL PRIVILEGES ON", "")
