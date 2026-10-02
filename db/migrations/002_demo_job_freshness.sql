-- Idempotent freshness and source identity fields for scheduled demo syncs.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_job_id TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS board_token TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS is_open BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS consecutive_misses INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS relevance_reasons TEXT[] NOT NULL DEFAULT '{}';

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_source_identity
    ON jobs (source, board_token, source_job_id)
    WHERE board_token IS NOT NULL AND source_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_demo_open_freshness
    ON jobs (is_demo, is_open, posted_at DESC, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS sync_runs (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    board_token TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    fetched_count INTEGER NOT NULL DEFAULT 0,
    relevant_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    closed_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);
