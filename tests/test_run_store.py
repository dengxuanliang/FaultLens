from __future__ import annotations

from pathlib import Path
import sqlite3

from faultlens.scale.run_store import RunStore
from faultlens.scale.schema import SCHEMA_VERSION


def test_run_store_initializes_required_tables(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run.db").open()
    try:
        tables = store.list_tables()
    finally:
        store.close()

    assert {
        "run_metadata",
        "input_files",
        "ingest_events",
        "run_warnings",
        "joined_cases",
        "analysis_jobs",
        "deterministic_results",
        "llm_attempts",
        "final_results",
    } <= tables


def test_run_store_persists_run_metadata_versions(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run.db").open()
    try:
        store.initialize_run_metadata(
            analysis_version="det-v1",
            prompt_version="prompt-v1",
            settings={
                "model": None,
                "llm_max_workers": 1,
                "llm_max_retries": 2,
                "llm_retry_backoff_seconds": 2,
                "llm_retry_on_5xx": True,
            },
        )
        row = store.load_run_metadata()
    finally:
        store.close()

    assert row["analysis_version"] == "det-v1"
    assert row["prompt_version"] == "prompt-v1"
    assert row["settings_json"]["llm_max_workers"] == 1


def test_run_store_rejects_changed_input_manifest(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run.db").open()
    try:
        store.record_input_file(
            path="a.jsonl",
            declared_order=0,
            detected_role="inference",
            size_bytes=10,
            mtime_epoch=1.0,
            sha256="old",
            sample_record_count=1,
        )
        store.initialize_run_metadata(
            analysis_version="det-v1",
            prompt_version="prompt-v1",
            settings={
                "model": None,
                "llm_max_workers": 1,
                "llm_max_retries": 2,
                "llm_retry_backoff_seconds": 2,
                "llm_retry_on_5xx": True,
            },
        )
        try:
            store.assert_resume_safe(
                current_inputs=[
                    {
                        "path": "a.jsonl",
                        "declared_order": 0,
                        "detected_role": "inference",
                        "size_bytes": 10,
                        "mtime_epoch": 1.0,
                        "sha256": "new",
                        "sample_record_count": 1,
                    }
                ],
                analysis_version="det-v1",
                prompt_version="prompt-v1",
                settings={
                    "model": None,
                    "llm_max_workers": 1,
                    "llm_max_retries": 2,
                    "llm_retry_backoff_seconds": 2,
                    "llm_retry_on_5xx": True,
                },
            )
        except ValueError as exc:
            assert "input manifest mismatch" in str(exc)
        else:
            raise AssertionError("expected input manifest mismatch")
    finally:
        store.close()


def test_run_store_requeues_expired_llm_jobs(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run.db").open()
    try:
        store.ensure_analysis_job(case_id="2", job_status="llm_running")
        store.update_job_lease(
            case_id="2",
            lease_token="lease-1",
            lease_until="2000-01-01T00:00:00+00:00",
        )
        store.requeue_expired_leases(now="2026-04-03T00:00:00+00:00")
        job = store.get_job("2")
    finally:
        store.close()

    assert job["job_status"] == "llm_pending"
    assert job["worker_lease_token"] is None


def test_run_store_records_ingest_events(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run.db").open()
    try:
        store.record_ingest_event(
            source_path="input.jsonl",
            line_number=3,
            severity="warning",
            event_type="bad_json",
            message="bad json at line 3 in input.jsonl",
            payload_excerpt='{"broken":',
        )
        events = store.list_ingest_events()
    finally:
        store.close()

    assert len(events) == 1
    assert events[0]["event_type"] == "bad_json"
    assert events[0]["line_number"] == 3


def test_run_store_records_run_warnings(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run.db").open()
    try:
        store.record_run_warning(stage="preflight", message="schema outlier at line 1 in inference.jsonl")
        warnings = store.list_run_warnings()
    finally:
        store.close()

    assert warnings == [
        {
            "id": 1,
            "stage": "preflight",
            "severity": "warning",
            "message": "schema outlier at line 1 in inference.jsonl",
            "created_at": warnings[0]["created_at"],
        }
    ]


def test_run_store_migrates_v1_database_to_latest_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(str(db_path))
    try:
        connection.executescript(
            """
            CREATE TABLE run_metadata (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                faultlens_version TEXT,
                schema_version INTEGER NOT NULL,
                analysis_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                git_commit TEXT
            );
            INSERT INTO run_metadata(
                run_id,
                created_at,
                faultlens_version,
                schema_version,
                analysis_version,
                prompt_version,
                settings_json,
                git_commit
            ) VALUES (
                'legacy-run',
                '2026-04-04T00:00:00+00:00',
                '0.1.0',
                1,
                'det-v1',
                'prompt-v1',
                '{}',
                NULL
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    store = RunStore(db_path).open()
    try:
        metadata = store.load_run_metadata()
        tables = store.list_tables()
        store.record_run_warning(stage="preflight", message="legacy warning")
        warnings = store.list_run_warnings()
    finally:
        store.close()

    assert metadata["schema_version"] == SCHEMA_VERSION
    assert "run_warnings" in tables
    assert warnings[0]["message"] == "legacy warning"


def test_run_store_records_response_path_without_inline_raw_body(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run.db").open()
    try:
        store.record_llm_attempt(
            case_id="2",
            attempt_index=1,
            request_messages=[{"role": "system", "content": "x"}],
            provider_model="m",
            provider_base_url="http://invalid.local",
            started_at="2026-04-04T00:00:00+00:00",
            finished_at="2026-04-04T00:00:01+00:00",
            outcome="strict_json",
            parse_mode="strict_json",
            parse_reason=None,
            response_text=None,
            response_path="llm_raw_responses/2.txt",
            response_sha256="abc123",
            error_type=None,
            error_message=None,
            http_status=None,
        )
        attempts = store.list_llm_attempts("2")
    finally:
        store.close()

    assert attempts[0]["response_text"] is None
    assert attempts[0]["response_path"] == "llm_raw_responses/2.txt"
