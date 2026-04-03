from __future__ import annotations

from pathlib import Path

from faultlens.scale.run_store import RunStore


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
            settings={"llm_max_workers": 1},
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
            settings={"llm_max_workers": 1},
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
