import json
import threading
import time
from pathlib import Path

from faultlens.cli import main


def _write_large_fixture(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_cli_resume_skips_already_checkpointed_cases(tmp_path: Path):
    inference_path = tmp_path / "inference.jsonl"
    results_path = tmp_path / "results.jsonl"
    output_dir = tmp_path / "outputs"

    inference_rows = []
    results_rows = []
    for case_id in range(1, 5):
        inference_rows.append(
            {
                "id": case_id,
                "content": f"Double {case_id}",
                "canonical_solution": "def solve(x):\n    return x * 2",
                "labels": {"programming_language": "python", "execution_language": "python"},
                "test": {"code": "assert solve(2) == 4\nassert solve(7) == 14"},
                "completion": "```python\ndef solve(x):\n    return x + 2\n```",
            }
        )
        results_rows.append(
            {
                "task_id": case_id,
                "accepted": False,
                "passed_at_1": 0,
                "pass_at_k": 0,
                "all_k_correct": 0,
                "n": 1,
                "programming_language": "python",
            }
        )

    _write_large_fixture(inference_path, inference_rows)
    _write_large_fixture(results_path, results_rows)

    first = main(
        [
            "analyze",
            "--input",
            str(inference_path),
            str(results_path),
            "--output-dir",
            str(output_dir),
            "--api-key",
            "k",
            "--base-url",
            "http://invalid.local",
            "--model",
            "m",
            "--llm-max-workers",
            "2",
            "--resume",
        ]
    )
    assert first == 0

    checkpoint_path = output_dir / "faultlens_checkpoint.sqlite3"
    assert checkpoint_path.exists()

    call_count = {"value": 0}

    class CountingClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = None
            self.last_completion_info = {}

        def complete_json(self, messages):
            call_count["value"] += 1
            self.last_completion_info = {"status": "strict_json", "invalid_reason": None, "raw_response_excerpt": "{\"root_cause\":\"solution_incorrect\"}"}
            return {"root_cause": "solution_incorrect", "explanation": "logic mismatch", "observable_evidence": ["assert failed"], "improvement_hints": [], "llm_signals": ["json"], "evidence_refs": [{"source": "tests"}]}

    import faultlens.orchestrator as orchestrator

    original = orchestrator.LLMClient
    orchestrator.LLMClient = CountingClient
    try:
        second = main(
            [
                "analyze",
                "--input",
                str(inference_path),
                str(results_path),
                "--output-dir",
                str(output_dir),
                "--api-key",
                "k",
                "--base-url",
                "http://invalid.local",
                "--model",
                "m",
                "--llm-max-workers",
                "2",
                "--resume",
            ]
        )
    finally:
        orchestrator.LLMClient = original

    assert second == 0
    assert call_count["value"] == 0


def test_cli_uses_bounded_llm_worker_concurrency(tmp_path: Path):
    inference_path = tmp_path / "inference.jsonl"
    results_path = tmp_path / "results.jsonl"
    output_dir = tmp_path / "outputs"

    inference_rows = []
    results_rows = []
    for case_id in range(1, 7):
        inference_rows.append(
            {
                "id": case_id,
                "content": f"Double {case_id}",
                "canonical_solution": "def solve(x):\n    return x * 2",
                "labels": {"programming_language": "python", "execution_language": "python"},
                "test": {"code": "assert solve(2) == 4\nassert solve(7) == 14"},
                "completion": "```python\ndef solve(x):\n    return x + 2\n```",
            }
        )
        results_rows.append(
            {
                "task_id": case_id,
                "accepted": False,
                "passed_at_1": 0,
                "pass_at_k": 0,
                "all_k_correct": 0,
                "n": 1,
                "programming_language": "python",
            }
        )

    _write_large_fixture(inference_path, inference_rows)
    _write_large_fixture(results_path, results_rows)

    import faultlens.orchestrator as orchestrator

    active = {"current": 0, "max": 0}
    lock = threading.Lock()

    class SlowClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = None
            self.last_completion_info = {}

        def complete_json(self, messages):
            with lock:
                active["current"] += 1
                active["max"] = max(active["max"], active["current"])
            time.sleep(0.05)
            with lock:
                active["current"] -= 1
            self.last_completion_info = {"status": "strict_json", "invalid_reason": None, "raw_response_excerpt": "{\"root_cause\":\"solution_incorrect\"}"}
            return {"root_cause": "solution_incorrect", "explanation": "logic mismatch", "observable_evidence": ["assert failed"], "improvement_hints": [], "llm_signals": ["json"], "evidence_refs": [{"source": "tests"}]}

    original = orchestrator.LLMClient
    orchestrator.LLMClient = SlowClient
    try:
        exit_code = main(
            [
                "analyze",
                "--input",
                str(inference_path),
                str(results_path),
                "--output-dir",
                str(output_dir),
                "--api-key",
                "k",
                "--base-url",
                "http://invalid.local",
                "--model",
                "m",
                "--llm-max-workers",
                "3",
                "--resume",
            ]
        )
    finally:
        orchestrator.LLMClient = original

    assert exit_code == 0
    assert 1 < active["max"] <= 3
