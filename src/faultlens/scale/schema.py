from __future__ import annotations

SCHEMA_VERSION = 1


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS run_metadata (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    faultlens_version TEXT,
    schema_version INTEGER NOT NULL,
    analysis_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    git_commit TEXT
);

CREATE TABLE IF NOT EXISTS input_files (
    path TEXT PRIMARY KEY,
    declared_order INTEGER NOT NULL,
    detected_role TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime_epoch REAL NOT NULL,
    sha256 TEXT NOT NULL,
    sample_record_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT,
    line_number INTEGER,
    severity TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_excerpt TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS joined_cases (
    case_id TEXT PRIMARY KEY,
    join_status TEXT NOT NULL,
    inference_line_number INTEGER,
    results_line_number INTEGER,
    input_role_detection TEXT,
    inference_payload_json TEXT,
    results_payload_json TEXT,
    normalization_warnings_json TEXT NOT NULL,
    normalization_errors_json TEXT NOT NULL,
    join_anomaly_flags_json TEXT NOT NULL,
    content_sha256 TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_jobs (
    case_id TEXT PRIMARY KEY,
    job_status TEXT NOT NULL,
    eligible_for_llm INTEGER,
    deterministic_ready INTEGER,
    llm_required INTEGER,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    worker_lease_token TEXT,
    worker_lease_until TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deterministic_results (
    case_id TEXT PRIMARY KEY,
    case_status TEXT NOT NULL,
    failure_gate_warnings_json TEXT NOT NULL,
    deterministic_signals_json TEXT NOT NULL,
    deterministic_findings_json TEXT NOT NULL,
    deterministic_root_cause_hint TEXT,
    runner_warnings_json TEXT NOT NULL,
    analysis_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    attempt_index INTEGER NOT NULL,
    request_messages_json TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    provider_model TEXT,
    provider_base_url TEXT,
    http_status INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    latency_ms INTEGER,
    outcome TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    response_text TEXT,
    response_sha256 TEXT,
    parse_mode TEXT,
    parse_reason TEXT,
    is_selected INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS final_results (
    case_id TEXT PRIMARY KEY,
    final_result_json TEXT NOT NULL,
    final_decision_source TEXT NOT NULL,
    root_cause TEXT,
    secondary_cause TEXT,
    confidence REAL,
    needs_human_review INTEGER NOT NULL,
    review_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_analysis_jobs_status ON analysis_jobs(job_status);
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_retry_at ON analysis_jobs(next_retry_at);
CREATE INDEX IF NOT EXISTS idx_llm_attempts_case_id ON llm_attempts(case_id);
"""


def initialize_schema(connection) -> None:
    connection.executescript(SCHEMA_SQL)
