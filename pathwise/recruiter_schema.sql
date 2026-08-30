-- Recruiter account data plane (Turso / libSQL).
-- Apply via pathwise.recruiter_accounts.apply_recruiter_schema.
-- Do not auto-migrate on game start.

CREATE TABLE IF NOT EXISTS recruiters (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    billing_date TEXT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    trial_active INTEGER NOT NULL DEFAULT 0,
    billing_exempt INTEGER NOT NULL DEFAULT 1,
    tier TEXT NOT NULL DEFAULT 'basic',
    company TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_recruiters_email ON recruiters(email);

CREATE TABLE IF NOT EXISTS recruiter_sessions (
    id TEXT PRIMARY KEY,
    recruiter_id TEXT NOT NULL REFERENCES recruiters(id),
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
