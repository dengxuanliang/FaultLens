from pathlib import Path

import pytest

from faultlens.ingest.jsonl import load_jsonl
from faultlens.ingest.resolver import detect_input_roles
from faultlens.normalize.joiner import build_ingest_snapshot
from faultlens.scale.run_store import RunStore


def _fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


def test_load_jsonl_reports_bad_line_number() -> None:
    result = load_jsonl(_fixtures_dir() / "broken_inference_sample.jsonl")

    assert len(result.records) == 2
    assert any("line 2" in warning for warning in result.warnings)


def test_detect_input_roles_from_schema() -> None:
    fixtures = _fixtures_dir()
    resolved = detect_input_roles(
        [fixtures / "results_sample.jsonl", fixtures / "inference_sample.jsonl"]
    )

    assert resolved.inference_path.name == "inference_sample.jsonl"
    assert resolved.results_path.name == "results_sample.jsonl"


def test_detect_input_roles_raises_for_ambiguous_inputs() -> None:
    fixtures = _fixtures_dir()

    with pytest.raises(ValueError, match="ambiguous"):
        detect_input_roles(
            [
                fixtures / "ambiguous_input_a.jsonl",
                fixtures / "ambiguous_input_b.jsonl",
            ]
        )


def test_detect_input_roles_scans_past_outlier_first_record(tmp_path: Path) -> None:
    left = tmp_path / "left.jsonl"
    right = tmp_path / "right.jsonl"
    left.write_text(
        '{"junk":1}\n'
        '{"id":1,"content":"c","canonical_solution":"x","completion":"y"}\n',
        encoding="utf-8",
    )
    right.write_text('{"task_id":1,"accepted":false}\n', encoding="utf-8")

    resolved = detect_input_roles([left, right])

    assert resolved.inference_path == left
    assert resolved.detected_roles[str(left)] == "inference"


def test_build_ingest_snapshot_persists_structured_ingest_events(tmp_path: Path) -> None:
    inference_path = tmp_path / "inference.jsonl"
    results_path = tmp_path / "results.jsonl"
    inference_path.write_text(
        '{"id":1,"content":"c","canonical_solution":"x","completion":"y"}\n'
        '{"broken":\n'
        '\n',
        encoding="utf-8",
    )
    results_path.write_text(
        '{"task_id":1,"accepted":false}\n'
        '{"task_id":2,"accepted":false}\n',
        encoding="utf-8",
    )

    store = RunStore(tmp_path / "run.db").open()
    try:
        build_ingest_snapshot(store, inference_path, results_path)
        events = store.list_ingest_events()
    finally:
        store.close()

    event_types = {event["event_type"] for event in events}
    assert "bad_json" in event_types
    assert "empty_line" in event_types
    assert "missing_pair" in event_types
