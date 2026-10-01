CREATE TYPE job_status AS ENUM (
    'discovered',
    'applied',
    'interviewing',
    'offer',
    'rejected',
    'withdrawn'
);

CREATE TABLE jobs (
    id SERIAL PRIMARY KEY,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    description TEXT,
    status job_status NOT NULL DEFAULT 'discovered',
    ats_score NUMERIC(5, 2),
    location TEXT,
    posted_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    track TEXT,
    eval_summary TEXT,
    evaluated_at TIMESTAMPTZ
    ,job_family TEXT NOT NULL DEFAULT 'other'
    ,employment_type TEXT NOT NULL DEFAULT 'unknown'
    ,work_mode TEXT NOT NULL DEFAULT 'unknown'
    ,experience_level TEXT NOT NULL DEFAULT 'unknown'
    ,sponsorship_status TEXT NOT NULL DEFAULT 'not_specified'
    ,visa_categories TEXT[] NOT NULL DEFAULT '{}'
    ,is_demo BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX idx_jobs_status ON jobs (status);
CREATE INDEX idx_jobs_company ON jobs (company);
CREATE INDEX idx_jobs_discovery_filters ON jobs
    (job_family, employment_type, work_mode, experience_level, sponsorship_status);

-- Phase 5: candidate profile + answer bank

CREATE TABLE candidate_profile (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
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

CREATE TABLE approved_answers (
    id SERIAL PRIMARY KEY,
    question_key TEXT NOT NULL UNIQUE,
    question_label TEXT NOT NULL,
    answer TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'user_approved',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Groq/OpenRouter LLM routing integration: audit trail, one row per routed LLM call.

CREATE TABLE llm_evaluations (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id),
    agent_name TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    evaluation_source TEXT NOT NULL,
    evaluation_status TEXT NOT NULL,
    prompt_version TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    estimated_cost NUMERIC(10, 6),
    latency_ms NUMERIC(10, 2),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    retry_count INTEGER NOT NULL DEFAULT 0,
    fallback_used BOOLEAN NOT NULL DEFAULT false,
    original_provider TEXT,
    final_provider TEXT,
    confidence NUMERIC(4, 3),
    validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    safe_error_message TEXT,
    result_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_llm_evaluations_job_id ON llm_evaluations (job_id);
CREATE INDEX idx_llm_evaluations_status ON llm_evaluations (evaluation_status);
