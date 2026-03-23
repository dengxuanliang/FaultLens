from pathlib import Path

import pytest

from faultlens.ingest.jsonl import load_jsonl
from faultlens.ingest.resolver import detect_input_roles


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
