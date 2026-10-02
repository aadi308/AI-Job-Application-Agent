-- Idempotent multi-user ownership and quota foundation.
CREATE TABLE IF NOT EXISTS user_candidate_profiles (
    owner_id TEXT PRIMARY KEY,
    contact JSONB NOT NULL DEFAULT '{}'::jsonb,
    education JSONB NOT NULL DEFAULT '[]'::jsonb,
    employment JSONB NOT NULL DEFAULT '[]'::jsonb,
    projects JSONB NOT NULL DEFAULT '[]'::jsonb,
    skills JSONB NOT NULL DEFAULT '[]'::jsonb,
    certifications JSONB NOT NULL DEFAULT '[]'::jsonb,
    work_authorization JSONB NOT NULL DEFAULT '{}'::jsonb,
    preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
    approved BOOLEAN NOT NULL DEFAULT false,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_approved_answers (
    owner_id TEXT NOT NULL,
    question_key TEXT NOT NULL,
    question_label TEXT NOT NULL,
    answer TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'user_approved',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, question_key)
);

CREATE TABLE IF NOT EXISTS user_job_state (
    owner_id TEXT NOT NULL,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status job_status NOT NULL DEFAULT 'discovered',
    ats_score NUMERIC(5, 2),
    track TEXT,
    eval_summary TEXT,
    evaluated_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, job_id)
);

CREATE TABLE IF NOT EXISTS user_artifacts (
    owner_id TEXT NOT NULL,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    resume_json JSONB,
    resume_text TEXT,
    resume_pdf BYTEA,
    outreach_text TEXT,
    claim_validation JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, job_id)
);

CREATE TABLE IF NOT EXISTS usage_events (
    id BIGSERIAL PRIMARY KEY,
    owner_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('ats_evaluation', 'resume_generation')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_usage_events_daily
    ON usage_events (owner_id, action, created_at DESC);

ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS owner_id TEXT;
CREATE INDEX IF NOT EXISTS idx_llm_evaluations_owner_id
    ON llm_evaluations (owner_id, created_at DESC);
