CREATE SCHEMA bot_state;
REVOKE ALL ON SCHEMA bot_state FROM PUBLIC;

CREATE TABLE bot_state.users (
  max_user_id TEXT PRIMARY KEY CHECK (max_user_id ~ '^[0-9]+$'),
  subscription_status TEXT NOT NULL DEFAULT 'inactive'
    CHECK (subscription_status IN ('inactive', 'active', 'cancelled')),
  subscription_expires_at TIMESTAMPTZ,
  plate_last_digit SMALLINT CHECK (plate_last_digit BETWEEN 0 AND 9),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (subscription_status <> 'active' OR subscription_expires_at IS NOT NULL)
);

CREATE TABLE bot_state.plate_input_states (
  max_user_id TEXT PRIMARY KEY REFERENCES bot_state.users(max_user_id) ON DELETE CASCADE,
  state TEXT NOT NULL CHECK (state = 'awaiting_plate'),
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bot_state.user_rate_limits (
  max_user_id TEXT PRIMARY KEY REFERENCES bot_state.users(max_user_id) ON DELETE CASCADE,
  last_lookup_at TIMESTAMPTZ,
  recent_lookup_at TIMESTAMPTZ[] NOT NULL DEFAULT ARRAY[]::TIMESTAMPTZ[],
  daily_service_date DATE NOT NULL,
  daily_lookup_count SMALLINT NOT NULL DEFAULT 0 CHECK (daily_lookup_count BETWEEN 0 AND 100),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (cardinality(recent_lookup_at) <= 20)
);

CREATE TABLE bot_state.callback_receipts (
  max_user_id TEXT NOT NULL REFERENCES bot_state.users(max_user_id) ON DELETE CASCADE,
  callback_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('processing', 'completed')),
  lease_expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMPTZ,
  PRIMARY KEY (max_user_id, callback_id),
  CHECK (
    (status = 'processing' AND lease_expires_at IS NOT NULL)
    OR (status = 'completed' AND completed_at IS NOT NULL)
  )
);
CREATE INDEX callback_receipts_completed_at_idx
  ON bot_state.callback_receipts (completed_at)
  WHERE status = 'completed';

REVOKE ALL ON ALL TABLES IN SCHEMA bot_state FROM PUBLIC;
