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
