from __future__ import annotations

SCHEMA_VERSION = 3


BASE_SCHEMA_SQL = """
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
    case_json TEXT NOT NULL,
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
    response_path TEXT,
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


def _migration_1_to_2(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS run_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _migration_2_to_3(connection) -> None:
    has_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'llm_attempts' LIMIT 1"
    ).fetchone()
    if not has_table:
        return
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(llm_attempts)").fetchall()
    }
    if "response_path" not in columns:
        connection.execute("ALTER TABLE llm_attempts ADD COLUMN response_path TEXT")


MIGRATIONS = {
    1: _migration_1_to_2,
    2: _migration_2_to_3,
}


def initialize_schema(connection) -> None:
    current_version = _detect_schema_version(connection)
    if current_version == 0:
        connection.executescript(BASE_SCHEMA_SQL)
        _set_schema_version(connection, 1)
        current_version = 1

    while current_version < SCHEMA_VERSION:
        migration = MIGRATIONS.get(current_version)
        if migration is None:
            raise RuntimeError(f"missing schema migration from version {current_version}")
        migration(connection)
        current_version += 1
        _set_schema_version(connection, current_version)

    connection.executescript(BASE_SCHEMA_SQL)
    if current_version >= 2:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS run_warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stage TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _detect_schema_version(connection) -> int:
    has_run_metadata = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'run_metadata' LIMIT 1"
    ).fetchone()
    if not has_run_metadata:
        return 0

    row = connection.execute("SELECT MAX(schema_version) AS value FROM run_metadata").fetchone()
    if row is not None and row["value"] is not None:
        return int(row["value"])

    pragma_row = connection.execute("PRAGMA user_version").fetchone()
    if pragma_row is None:
        return 1
    value = pragma_row[0] if not isinstance(pragma_row, dict) else pragma_row.get("user_version")
    return int(value or 1)


def _set_schema_version(connection, version: int) -> None:
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'run_metadata' LIMIT 1"
    ).fetchone():
        connection.execute("UPDATE run_metadata SET schema_version = ?", (version,))
    connection.execute(f"PRAGMA user_version = {version}")
