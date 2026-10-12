-- Tether proof certificate storage schema.
-- Applied automatically via CNPG postInitSQL in postgresql-cluster.yaml.
-- Kept here as reference for manual setup or migrations.

CREATE TABLE IF NOT EXISTS proof_certificates (
  id            SERIAL PRIMARY KEY,
  trace_id      TEXT NOT NULL,
  content_hash  TEXT NOT NULL,
  rule_used     TEXT NOT NULL,
  properties    TEXT[] NOT NULL,
  obs_count     INTEGER NOT NULL,
  status        TEXT NOT NULL,
  violations    TEXT[],
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cert_trace ON proof_certificates(trace_id);
CREATE INDEX IF NOT EXISTS idx_cert_created ON proof_certificates(created_at);

-- Proxy verification results — tracks automatic rule classification
-- at the RHOAI KServe inference boundary.
CREATE TABLE IF NOT EXISTS proxy_verifications (
  id               SERIAL PRIMARY KEY,
  trace_id         TEXT NOT NULL,
  request_hash     TEXT NOT NULL,
  classified_rule  TEXT NOT NULL,
  obs_count        INTEGER NOT NULL,
  status           TEXT NOT NULL,
  conclusion_preview TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_proxy_trace ON proxy_verifications(trace_id);
CREATE INDEX IF NOT EXISTS idx_proxy_created ON proxy_verifications(created_at);
