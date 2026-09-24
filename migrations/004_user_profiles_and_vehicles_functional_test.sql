-- Connect separately as bot_state_writer. This leaves no rows after ROLLBACK.
BEGIN;
INSERT INTO bot_state.users (max_user_id) VALUES ('9900000000000000001') ON CONFLICT DO NOTHING;
INSERT INTO bot_state.user_vehicles (max_user_id, plate_normalized, plate_last_digit)
VALUES ('9900000000000000001', 'А111АА56', 1), ('9900000000000000001', 'А222АА56', 2), ('9900000000000000001', 'А333АА56', 3);
DO $$
BEGIN
  BEGIN
    INSERT INTO bot_state.user_vehicles (max_user_id, plate_normalized, plate_last_digit)
    VALUES ('9900000000000000001', 'А444АА56', 4);
    RAISE EXCEPTION 'fourth vehicle was accepted';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  BEGIN
    INSERT INTO bot_state.user_vehicles (max_user_id, plate_normalized, plate_last_digit)
    VALUES ('9900000000000000001', 'А111АА56', 1);
    RAISE EXCEPTION 'duplicate vehicle was accepted';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END;
$$;
ROLLBACK;
