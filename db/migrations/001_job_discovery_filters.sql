-- Safe to run repeatedly against existing local or hosted databases.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_family TEXT NOT NULL DEFAULT 'other';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS employment_type TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS work_mode TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS experience_level TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS sponsorship_status TEXT NOT NULL DEFAULT 'not_specified';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS visa_categories TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_jobs_discovery_filters ON jobs
    (job_family, employment_type, work_mode, experience_level, sponsorship_status);
