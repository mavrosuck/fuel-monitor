CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE processed_source_messages (
  source_key TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL,
  source_chat_id TEXT NOT NULL,
  source_message_id TEXT NOT NULL,
  message_date TIMESTAMPTZ NOT NULL,
  content_hash TEXT NOT NULL,
  processing_status TEXT NOT NULL CHECK (processing_status IN ('pending', 'processing', 'done', 'duplicate', 'failed')),
  processed_at TIMESTAMPTZ,
  canonical_source_key TEXT REFERENCES processed_source_messages(source_key),
  processing_started_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_processed_source_messages_content_hash ON processed_source_messages (content_hash);
CREATE INDEX ix_processed_source_messages_status ON processed_source_messages (processing_status);
CREATE TABLE fuel_facts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_key TEXT NOT NULL REFERENCES processed_source_messages(source_key) ON DELETE CASCADE,
  station_normalized TEXT NOT NULL,
  station_brand TEXT,
  station_location TEXT,
  fuel_type TEXT NOT NULL CHECK (fuel_type IN ('ai_92', 'ai_95', 'ai_100', 'diesel', 'gas')),
  state TEXT NOT NULL CHECK (state IN ('available', 'limited', 'unavailable')),
  price_text TEXT, queue_text TEXT, queue_cars INTEGER, restrictions JSONB NOT NULL DEFAULT '[]'::jsonb,
  additional_info TEXT, observed_at TIMESTAMPTZ NOT NULL, observed_time_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_fuel_facts_source_station_fuel UNIQUE (source_key, station_normalized, fuel_type)
);
CREATE INDEX ix_fuel_facts_station_fuel_observed_at ON fuel_facts (station_normalized, fuel_type, observed_at);
CREATE INDEX ix_fuel_facts_fuel_observed_at ON fuel_facts (fuel_type, observed_at);
