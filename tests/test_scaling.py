import json
import threading
import time
from pathlib import Path

import pytest

from faultlens.cli import main
from faultlens.orchestrator import _assert_supported_case_volume
from faultlens.scale.run_store import RunStore


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
        ]
    )
    assert first == 0
    assert not (output_dir / "faultlens_checkpoint.sqlite3").exists()

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


def test_cli_resume_rejects_runtime_setting_drift(tmp_path: Path):
    inference_path = tmp_path / "inference.jsonl"
    results_path = tmp_path / "results.jsonl"
    output_dir = tmp_path / "outputs"

    _write_large_fixture(
        inference_path,
        [
            {
                "id": 1,
                "content": "Double 1",
                "canonical_solution": "def solve(x):\n    return x * 2",
                "labels": {"programming_language": "python", "execution_language": "python"},
                "test": {"code": "assert solve(2) == 4\nassert solve(7) == 14"},
                "completion": "```python\ndef solve(x):\n    return x + 2\n```",
            }
        ],
    )
    _write_large_fixture(
        results_path,
        [
            {
                "task_id": 1,
                "accepted": False,
                "passed_at_1": 0,
                "pass_at_k": 0,
                "all_k_correct": 0,
                "n": 1,
                "programming_language": "python",
            }
        ],
    )

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
            "--llm-max-retries",
            "2",
        ]
    )
    assert first == 0

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
            "--llm-max-retries",
            "5",
            "--resume",
        ]
    )

    assert second == 3


def test_cli_retries_retryable_llm_jobs_only_after_backoff_window(tmp_path: Path, monkeypatch):
    inference_path = tmp_path / "inference.jsonl"
    results_path = tmp_path / "results.jsonl"
    output_dir = tmp_path / "outputs"

    _write_large_fixture(
        inference_path,
        [
            {
                "id": 1,
                "content": "Double 1",
                "canonical_solution": "def solve(x):\n    return x * 2",
                "labels": {"programming_language": "python", "execution_language": "python"},
                "test": {"code": "assert solve(2) == 4\nassert solve(7) == 14"},
                "completion": "```python\ndef solve(x):\n    return x + 2\n```",
            }
        ],
    )
    _write_large_fixture(
        results_path,
        [
            {
                "task_id": 1,
                "accepted": False,
                "passed_at_1": 0,
                "pass_at_k": 0,
                "all_k_correct": 0,
                "n": 1,
                "programming_language": "python",
            }
        ],
    )

    import faultlens.orchestrator as orchestrator

    class RetryableFailingClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = "llm unavailable: rate limited"
            self.last_completion_info = {}

        def complete_json(self, messages):
            self.last_completion_info = {
                "status": "request_error",
                "error_type": "HTTPError",
                "invalid_reason": "HTTPError 429: Too Many Requests",
                "http_status": 429,
                "raw_response_excerpt": '{"error":{"message":"rate limit"}}',
                "raw_response_text": '{"error":{"message":"rate limit"}}',
                "raw_response_sha256": "rate",
            }
            return None

    monkeypatch.setattr(orchestrator, "LLMClient", RetryableFailingClient)
    monkeypatch.setattr(orchestrator, "_utcnow_iso", lambda: "2026-04-03T00:00:00+00:00")
    monkeypatch.setattr(orchestrator, "_future_iso", lambda *, seconds: "2026-04-03T00:05:00+00:00")

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
        ]
    )
    assert first == 0

    store = RunStore(output_dir / "run.db").open()
    try:
        job = store.get_job("1")
        assert job["job_status"] == "llm_failed_retryable"
        first_retry_at = job["next_retry_at"]
        assert first_retry_at
    finally:
        store.close()

    call_count = {"value": 0}

    class CountingSuccessClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = None
            self.last_completion_info = {}

        def complete_json(self, messages):
            call_count["value"] += 1
            self.last_completion_info = {
                "status": "strict_json",
                "invalid_reason": None,
                "raw_response_excerpt": "{\"root_cause\":\"solution_incorrect\"}",
                "raw_response_text": "{\"root_cause\":\"solution_incorrect\",\"explanation\":\"logic mismatch\",\"observable_evidence\":[\"assert failed\"],\"improvement_hints\":[],\"llm_signals\":[\"json\"],\"evidence_refs\":[{\"source\":\"tests\"}]}",
                "raw_response_sha256": "ok",
            }
            return {
                "root_cause": "solution_incorrect",
                "explanation": "logic mismatch",
                "observable_evidence": ["assert failed"],
                "improvement_hints": [],
                "llm_signals": ["json"],
                "evidence_refs": [{"source": "tests"}],
            }

    monkeypatch.setattr(orchestrator, "LLMClient", CountingSuccessClient)
    monkeypatch.setattr(orchestrator, "_utcnow_iso", lambda: "2026-04-03T00:00:30+00:00")
    monkeypatch.setattr(orchestrator, "_future_iso", lambda *, seconds: "2026-04-03T00:05:30+00:00")

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
            "--resume",
        ]
    )
    assert second == 0
    assert call_count["value"] == 0

    monkeypatch.setattr(orchestrator, "_utcnow_iso", lambda: "2026-04-03T00:05:30+00:00")
    monkeypatch.setattr(orchestrator, "_future_iso", lambda *, seconds: "2026-04-03T00:10:30+00:00")

    third = main(
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
            "--resume",
        ]
    )
    assert third == 0
    assert call_count["value"] == 1

    store = RunStore(output_dir / "run.db").open()
    try:
        job = store.get_job("1")
        assert job["job_status"] == "finalized"
        assert store.count_final_results() == 1
    finally:
        store.close()


def test_cli_stops_retryable_llm_jobs_after_max_retry_budget(tmp_path: Path, monkeypatch):
    inference_path = tmp_path / "inference.jsonl"
    results_path = tmp_path / "results.jsonl"
    output_dir = tmp_path / "outputs"

    _write_large_fixture(
        inference_path,
        [
            {
                "id": 1,
                "content": "Double 1",
                "canonical_solution": "def solve(x):\n    return x * 2",
                "labels": {"programming_language": "python", "execution_language": "python"},
                "test": {"code": "assert solve(2) == 4\nassert solve(7) == 14"},
                "completion": "```python\ndef solve(x):\n    return x + 2\n```",
            }
        ],
    )
    _write_large_fixture(
        results_path,
        [
            {
                "task_id": 1,
                "accepted": False,
                "passed_at_1": 0,
                "pass_at_k": 0,
                "all_k_correct": 0,
                "n": 1,
                "programming_language": "python",
            }
        ],
    )

    import faultlens.orchestrator as orchestrator

    class RetryableFailingClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = "llm unavailable: rate limited"
            self.last_completion_info = {}

        def complete_json(self, messages):
            self.last_completion_info = {
                "status": "request_error",
                "error_type": "HTTPError",
                "invalid_reason": "HTTPError 429: Too Many Requests",
                "http_status": 429,
                "raw_response_excerpt": '{"error":{"message":"rate limit"}}',
                "raw_response_text": '{"error":{"message":"rate limit"}}',
                "raw_response_sha256": "rate",
            }
            return None

    monkeypatch.setattr(orchestrator, "LLMClient", RetryableFailingClient)

    time_points = iter(
        [
            "2026-04-03T00:00:00+00:00",
            "2026-04-03T00:00:00+00:00",
            "2026-04-03T00:00:01+00:00",
            "2026-04-03T00:00:02+00:00",
            "2026-04-03T00:00:02+00:00",
            "2026-04-03T00:00:03+00:00",
        ]
    )
    monkeypatch.setattr(orchestrator, "_utcnow_iso", lambda: next(time_points))
    monkeypatch.setattr(orchestrator, "_future_iso", lambda *, seconds: "2026-04-03T00:05:00+00:00")

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
            "--llm-max-retries",
            "1",
        ]
    )
    assert first == 0

    monkeypatch.setattr(orchestrator, "_utcnow_iso", lambda: "2026-04-03T00:05:01+00:00")
    monkeypatch.setattr(orchestrator, "_future_iso", lambda *, seconds: "2026-04-03T00:10:01+00:00")

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
            "--llm-max-retries",
            "1",
            "--resume",
        ]
    )
    assert second == 0

    store = RunStore(output_dir / "run.db").open()
    try:
        attempts = store.list_llm_attempts("1")
        job = store.get_job("1")
    finally:
        store.close()

    assert len(attempts) == 2
    assert job["attempt_count"] == 2
    assert job["job_status"] == "finalized"
    assert job["next_retry_at"] is None

    third = main(
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
            "--llm-max-retries",
            "1",
            "--resume",
        ]
    )
    assert third == 0

    store = RunStore(output_dir / "run.db").open()
    try:
        attempts = store.list_llm_attempts("1")
    finally:
        store.close()

    assert len(attempts) == 2


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
            ]
        )
    finally:
        orchestrator.LLMClient = original

    assert exit_code == 0
    assert 1 < active["max"] <= 3


def test_cli_persists_run_store_snapshot(tmp_path: Path):
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

    exit_code = main(
        [
            "analyze",
            "--input",
            str(inference_path),
            str(results_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "run.db").exists()
    assert (output_dir / "input_manifest.json").exists()

    store = RunStore(output_dir / "run.db").open()
    try:
        assert store.count_joined_cases() == 4
        assert store.count_jobs() == 4
        metadata = store.load_run_metadata()
    finally:
        store.close()

    assert metadata["prompt_version"]


def test_cli_resume_uses_run_store_without_checkpoint_file(tmp_path: Path):
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
        ]
    )
    assert first == 0

    checkpoint_path = output_dir / "faultlens_checkpoint.sqlite3"
    if checkpoint_path.exists():
        checkpoint_path.unlink()

    call_count = {"value": 0}

    class CountingClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = None
            self.last_completion_info = {}

        def complete_json(self, messages):
            call_count["value"] += 1
            self.last_completion_info = {
                "status": "strict_json",
                "invalid_reason": None,
                "raw_response_excerpt": "{\"root_cause\":\"solution_incorrect\"}",
            }
            return {
                "root_cause": "solution_incorrect",
                "explanation": "logic mismatch",
                "observable_evidence": ["assert failed"],
                "improvement_hints": [],
                "llm_signals": ["json"],
                "evidence_refs": [{"source": "tests"}],
            }

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
                "--resume",
            ]
        )
    finally:
        orchestrator.LLMClient = original

    assert second == 0
    assert call_count["value"] == 0


def test_case_volume_guard_accepts_1000_cases():
    _assert_supported_case_volume(1000)


def test_cli_rejects_runs_larger_than_1000_cases(tmp_path: Path):
    inference_path = tmp_path / "inference.jsonl"
    results_path = tmp_path / "results.jsonl"
    output_dir = tmp_path / "outputs"

    inference_rows = []
    results_rows = []
    for case_id in range(1, 1002):
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

    exit_code = main(
        [
            "analyze",
            "--input",
            str(inference_path),
            str(results_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 3


def test_cli_resume_processes_llm_pending_jobs_without_rerunning_deterministic(tmp_path: Path, monkeypatch):
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

    import faultlens.orchestrator as orchestrator

    original_flush = orchestrator._flush_llm_batch

    def boom(**kwargs):
        raise RuntimeError("stop before llm persistence completes")

    monkeypatch.setattr(orchestrator, "_flush_llm_batch", boom)

    try:
        try:
            main(
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
                ]
            )
        except RuntimeError as exc:
            assert "stop before llm persistence completes" in str(exc)
        else:
            raise AssertionError("expected interrupted llm stage")
    finally:
        monkeypatch.setattr(orchestrator, "_flush_llm_batch", original_flush)

    store = RunStore(output_dir / "run.db").open()
    try:
        assert store.count_final_results() == 0
        assert store.count_jobs(status="llm_pending") == 4
    finally:
        store.close()

    deterministic_calls = {"value": 0}

    def fail_if_called(cases, execution_timeout=10):
        deterministic_calls["value"] += 1
        raise AssertionError("deterministic stage should not rerun for llm_pending jobs")

    class CountingClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = None
            self.last_completion_info = {}

        def complete_json(self, messages):
            self.last_completion_info = {
                "status": "strict_json",
                "invalid_reason": None,
                "raw_response_excerpt": "{\"root_cause\":\"solution_incorrect\"}",
                "raw_response_text": "{\"root_cause\":\"solution_incorrect\",\"explanation\":\"logic mismatch\",\"observable_evidence\":[\"assert failed\"],\"improvement_hints\":[],\"llm_signals\":[\"json\"],\"evidence_refs\":[{\"source\":\"tests\"}]}",
                "raw_response_sha256": "abc",
            }
            return {
                "root_cause": "solution_incorrect",
                "explanation": "logic mismatch",
                "observable_evidence": ["assert failed"],
                "improvement_hints": [],
                "llm_signals": ["json"],
                "evidence_refs": [{"source": "tests"}],
            }

    monkeypatch.setattr(orchestrator, "analyze_cases_deterministically", fail_if_called)
    monkeypatch.setattr(orchestrator, "LLMClient", CountingClient)

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
            "--resume",
        ]
    )

    assert exit_code == 0
    assert deterministic_calls["value"] == 0

    store = RunStore(output_dir / "run.db").open()
    try:
        assert store.count_final_results() == 4
    finally:
        store.close()


def test_cli_resume_rebuilds_selected_llm_result_from_response_file(tmp_path: Path, monkeypatch):
    inference_path = tmp_path / "inference.jsonl"
    results_path = tmp_path / "results.jsonl"
    output_dir = tmp_path / "outputs"

    _write_large_fixture(
        inference_path,
        [
            {
                "id": 1,
                "content": "Double 1",
                "canonical_solution": "def solve(x):\n    return x * 2",
                "labels": {"programming_language": "python", "execution_language": "python"},
                "test": {"code": "assert solve(2) == 4\nassert solve(7) == 14"},
                "completion": "```python\ndef solve(x):\n    return x + 2\n```",
            }
        ],
    )
    _write_large_fixture(
        results_path,
        [
            {
                "task_id": 1,
                "accepted": False,
                "passed_at_1": 0,
                "pass_at_k": 0,
                "all_k_correct": 0,
                "n": 1,
                "programming_language": "python",
            }
        ],
    )

    import faultlens.orchestrator as orchestrator

    class StrictJsonClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = None
            self.last_completion_info = {
                "status": "strict_json",
                "invalid_reason": None,
                "raw_response_excerpt": '{"root_cause":"solution_incorrect"}',
                "raw_response_text": '{"root_cause":"solution_incorrect","explanation":"logic mismatch","observable_evidence":["assert failed"],"improvement_hints":[],"llm_signals":["json"],"evidence_refs":[{"source":"tests"}]}',
                "raw_response_sha256": "abc123",
            }

        def complete_json(self, messages):
            return {
                "root_cause": "solution_incorrect",
                "explanation": "logic mismatch",
                "observable_evidence": ["assert failed"],
                "improvement_hints": [],
                "llm_signals": ["json"],
                "evidence_refs": [{"source": "tests"}],
            }

    monkeypatch.setattr(orchestrator, "LLMClient", StrictJsonClient)

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
        ]
    )
    assert first == 0

    store = RunStore(output_dir / "run.db").open()
    try:
        connection = store._require_connection()
        connection.execute("DELETE FROM final_results")
        connection.execute("UPDATE analysis_jobs SET job_status = 'llm_done' WHERE case_id = ?", ("1",))
        connection.commit()
    finally:
        store.close()
    (output_dir / "llm_raw_responses" / "1.txt").unlink()

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
            "--resume",
        ]
    )

    assert second == 0
    rows = [json.loads(line) for line in (output_dir / "case_analysis.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[0]["final_decision_source"] == "deterministic_plus_llm"
    assert rows[0]["root_cause"] == "solution_incorrect"
