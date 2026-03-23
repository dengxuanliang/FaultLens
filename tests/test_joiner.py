from pathlib import Path

from faultlens.normalize.joiner import join_records


def _fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


def test_join_records_merges_on_inference_id_and_results_task_id() -> None:
    fixtures = _fixtures_dir()
    joined = join_records(
        inference_path=fixtures / "inference_sample.jsonl",
        results_path=fixtures / "results_sample.jsonl",
    )

    assert len(joined) == 2
    assert joined[0]["case_id"] == "1"
    assert joined[0]["evaluation"]["accepted"] is True
    assert joined[0]["source"]["inference_line_number"] == 1
    assert joined[0]["source"]["results_line_number"] == 1
    assert joined[0]["raw"]["inference_record"]["id"] == 1
    assert joined[0]["raw"]["results_record"]["task_id"] == 1


def test_join_records_derives_slice_fields_and_metadata_conflict_warning() -> None:
    fixtures = _fixtures_dir()
    joined = join_records(
        inference_path=fixtures / "inference_sample.jsonl",
        results_path=fixtures / "results_sample.jsonl",
    )
    second = [record for record in joined if record["case_id"] == "2"][0]

    assert second["metadata"]["slice_fields"]["programming_language"] == "python"
    assert second["metadata"]["slice_fields"]["difficulty"] == "easy"
    assert any(
        "difficulty" in warning for warning in second["normalization"]["warnings"]
    )


def test_join_records_marks_missing_pair_as_join_issue(tmp_path: Path) -> None:
    inference_path = tmp_path / "inference.jsonl"
    results_path = tmp_path / "results.jsonl"
    inference_path.write_text(
        '{"id":1,"content":"c","canonical_solution":"x","completion":"y"}\n',
        encoding="utf-8",
    )
    results_path.write_text(
        '{"task_id":2,"accepted":false}\n',
        encoding="utf-8",
    )

    joined = join_records(inference_path=inference_path, results_path=results_path)

    assert len(joined) == 2
    assert all(record["case_status"] == "join_issue" for record in joined)
