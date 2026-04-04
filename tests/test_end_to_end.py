import json
from pathlib import Path

from faultlens.cli import main
from faultlens.orchestrator import finalize_outputs
from faultlens.scale.run_store import RunStore


def test_cli_analyze_generates_outputs(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "analyze",
            "--input",
            str(fixtures_dir / "inference_sample.jsonl"),
            str(fixtures_dir / "results_sample.jsonl"),
            "--output-dir",
            str(output_dir),
            "--case-id",
            "2",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "analysis_report.md").exists()
    assert (output_dir / "hierarchical_root_cause_report.md").exists()
    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert "# 输入警告" in report_text
    assert "# LLM 警告" in report_text
    assert "# LLM 响应质量" in report_text
    assert "# 三层错因聚合" in report_text
    hierarchy_report = (output_dir / "hierarchical_root_cause_report.md").read_text(encoding="utf-8")
    assert "# 三层错因总览" in hierarchy_report
    assert "# 主类到细类拆解" in hierarchy_report
    assert "# 根因与三层错因交叉映射" in hierarchy_report
    assert "# 待人工复核样本" in hierarchy_report
    assert (output_dir / "case_analysis.jsonl").exists()
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "run_metadata.json").exists()
    assert (output_dir / "cases" / "1.md").exists()
    assert (output_dir / "cases" / "2.md").exists()
    exemplar_dir = output_dir / "exemplars"
    assert exemplar_dir.exists()

    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert "# 运行摘要" in report_text
    assert "# 确定性分析摘要" in report_text
    assert "# LLM 根因分布" in report_text
    assert "# 交叉分析" in report_text
    assert "# 切片分析" in report_text
    assert "# 代表性案例" in report_text
    assert "# 待人工复核" in report_text
    assert "结论：" in report_text
    assert "●●●●●●●●●●" in report_text or "●●●●●○○○○○" in report_text or "●●○○○○○○○○" in report_text
    assert "| 类别 | 数量 | 占失败样本比例 | 图示 |" in report_text
    assert "| 类别 | 数量 | 占可归因失败比例 | 图示 |" in report_text
    assert "| 待复核数量 | 占失败样本比例 | 图示 | Case IDs |" in report_text
    assert "%" in report_text

    case_one_text = (output_dir / "cases" / "1.md").read_text(encoding="utf-8")
    assert "## 基本信息" in case_one_text
    assert "## 归因结论" in case_one_text

    case_text = (output_dir / "cases" / "2.md").read_text(encoding="utf-8")
    assert "## 归因结论" in case_text
    assert "## 解释" in case_text
    assert "## 解析 / 编译 / 测试" in case_text
    assert "## LLM 解析信息" in case_text
    assert "## 三层错因分析" in case_text

    rows = [json.loads(line) for line in (output_dir / "case_analysis.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {row["case_id"] for row in rows} == {"1", "2"}
    assert {
        path.stem for path in (output_dir / "cases").glob("*.md")
    } == {row["case_id"] for row in rows}
    failure = next(row for row in rows if row["case_id"] == "2")
    l1_code = failure["hierarchical_cause"]["l1"]["code"]
    assert l1_code in {"functional_semantic_error", "environment_evaluation_mismatch"}
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["hierarchy_counts"]["l1"][l1_code] == 1
    assert summary["hierarchy_subtype_counts"]["l1"][l1_code]
    assert summary["hierarchy_root_cause_cross"]["l1"][l1_code]


def test_cli_survives_llm_failure_and_falls_back(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"

    def boom(self, messages):
        raise RuntimeError("network down")

    monkeypatch.setattr("faultlens.llm.client.LLMClient.complete_json", boom)

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--api-key",
        "k",
        "--base-url",
        "http://invalid.local",
        "--model",
        "m",
    ])

    assert exit_code == 0
    assert (output_dir / "analysis_report.md").exists()
    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert "# 输入警告" in report_text
    assert "# LLM 警告" in report_text


def test_cli_persists_deterministic_results_in_run_store(tmp_path: Path, fixtures_dir: Path):
    output_dir = tmp_path / "outputs"

    exit_code = main(
        [
            "analyze",
            "--input",
            str(fixtures_dir / "inference_sample.jsonl"),
            str(fixtures_dir / "results_sample.jsonl"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0

    store = RunStore(output_dir / "run.db").open()
    try:
        row = store.get_deterministic_result("2")
        job = store.get_job("2")
    finally:
        store.close()

    assert row["case_status"] == "attributable_failure"
    assert "suspicious_eval_mismatch" in row["deterministic_signals_json"]
    assert row["deterministic_root_cause_hint"]
    assert job["job_status"] in {
        "deterministic_done",
        "llm_pending",
        "llm_done",
        "llm_failed_terminal",
        "llm_failed_retryable",
        "finalized",
    }
    assert job["deterministic_ready"] == 1


def test_cli_exports_case_analysis_from_final_results(tmp_path: Path, fixtures_dir: Path):
    output_dir = tmp_path / "outputs"

    exit_code = main(
        [
            "analyze",
            "--input",
            str(fixtures_dir / "inference_sample.jsonl"),
            str(fixtures_dir / "results_sample.jsonl"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0

    rows = [json.loads(line) for line in (output_dir / "case_analysis.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    store = RunStore(output_dir / "run.db").open()
    try:
        final_count = store.count_final_results()
        job = store.get_job("2")
    finally:
        store.close()

    assert len(rows) == final_count
    assert job["job_status"] in {"finalized", "llm_failed_retryable"}


def test_finalize_can_rerender_without_reprocessing_inputs(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "analyze",
            "--input",
            str(fixtures_dir / "inference_sample.jsonl"),
            str(fixtures_dir / "results_sample.jsonl"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0

    first_report = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    first_summary = (output_dir / "summary.json").read_text(encoding="utf-8")

    (output_dir / "analysis_report.md").write_text("stale", encoding="utf-8")
    (output_dir / "summary.json").write_text("stale", encoding="utf-8")

    finalize_outputs(output_dir=output_dir)

    second_report = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    second_summary = (output_dir / "summary.json").read_text(encoding="utf-8")

    assert second_report == first_report
    assert second_summary == first_summary


def test_cli_records_invalid_llm_response_stats_without_blocking(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"

    class FakeClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = None
            self.last_completion_info = {}

        def complete_json(self, messages):
            self.last_warning = "llm invalid response format: non_json_content"
            self.last_completion_info = {
                "status": "invalid",
                "invalid_reason": "non_json_content",
            }
            return None

    monkeypatch.setattr("faultlens.orchestrator.LLMClient", FakeClient)

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--api-key",
        "k",
        "--base-url",
        "http://invalid.local",
        "--model",
        "m",
    ])

    assert exit_code == 0

    run_metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
    stats = run_metadata["llm_response_stats"]
    assert stats["attempted"] == 1
    assert stats["strict_json"] == 0
    assert stats["adaptive_parse"] == 0
    assert stats["salvaged"] == 0
    assert stats["skipped_invalid"] == 1
    assert stats["nonconforming"] == 1
    assert stats["nonconforming_percentage"] == 100.0
    assert stats["nonconforming_reasons"] == {"non_json_content": 1}

    rows = [json.loads(line) for line in (output_dir / "case_analysis.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    failure = next(row for row in rows if row["case_id"] == "2")
    assert failure["final_decision_source"] == "deterministic_only"
    assert failure["hierarchical_cause"]["l1"]["code"] in {
        "functional_semantic_error",
        "environment_evaluation_mismatch",
    }
    assert failure["hierarchical_cause"]["analysis_basis"]["decision_source"] == "deterministic_only"

    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert "# LLM 响应质量" in report_text
    assert "non_json_content" in report_text


def test_case_report_surfaces_runner_degradation_warnings(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"

    class FakeClient:  # pragma: no cover - simple monkeypatch target
        pass

    def fake_analyze(cases, execution_timeout=10):
        analyzed = []
        for case in cases:
            case = dict(case)
            case["deterministic_findings"] = {
                "test_status": "unavailable",
                "compile_status": "unavailable",
                "runner_warnings": ["go toolchain unavailable or sandbox disabled"],
                "completion_code": "package main",
                "primary_language": "go",
                "canonical_diff_summary": "n/a",
                "test_harness_alignment_summary": "n/a",
            }
            case["deterministic_signals"] = ["suspicious_eval_mismatch"]
            case["deterministic_root_cause_hint"] = "possible_evaluation_mismatch"
            analyzed.append(case)
        return analyzed

    monkeypatch.setattr("faultlens.orchestrator.analyze_cases_deterministically", fake_analyze)

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--case-id",
        "2",
    ])

    assert exit_code == 0
    case_text = (output_dir / "cases" / "2.md").read_text(encoding="utf-8")
    assert "go toolchain unavailable or sandbox disabled" in case_text


def test_case_output_includes_raw_llm_excerpt_and_parse_metadata(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"
    raw_response = """Root Cause: solution incorrect
Explanation: The implementation adds 3 instead of doubling x.
Evidence:
- solve(7) returned 10
Improvement Hints:
- Use multiplication instead of addition.
"""

    class FakeClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = "llm response adapted: sectioned_text"
            self.last_completion_info = {
                "status": "adaptive_parse",
                "invalid_reason": "sectioned_text",
                "raw_response_excerpt": "Root Cause: solution incorrect",
                "raw_response_text": raw_response,
            }

        def complete_json(self, messages):
            return {
                "root_cause": "solution_incorrect",
                "explanation": "The implementation adds 3 instead of doubling x.",
                "observable_evidence": ["solve(7) returned 10"],
                "improvement_hints": ["Use multiplication instead of addition."],
                "llm_signals": ["adaptive_response_parser"],
                "evidence_refs": [{"source": "tests"}],
            }

    monkeypatch.setattr("faultlens.orchestrator.LLMClient", FakeClient)

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--api-key",
        "k",
        "--base-url",
        "http://invalid.local",
        "--model",
        "m",
    ])

    assert exit_code == 0
    rows = [json.loads(line) for line in (output_dir / "case_analysis.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    failure = next(row for row in rows if row["case_id"] == "2")
    assert failure["llm_parse_mode"] == "adaptive_parse"
    assert failure["llm_parse_reason"] == "sectioned_text"
    assert failure["llm_raw_response_excerpt"] == "Root Cause: solution incorrect"
    assert failure["llm_raw_response_path"] == "llm_raw_responses/2.txt"
    assert failure["llm_raw_response_sha256"]

    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert "raw_response_excerpts" in report_text

    case_text = (output_dir / "cases" / "2.md").read_text(encoding="utf-8")
    assert "Root Cause: solution incorrect" in case_text
    assert "llm_raw_responses/2.txt" in case_text

    raw_response_path = output_dir / "llm_raw_responses" / "2.txt"
    assert raw_response_path.exists()
    assert raw_response_path.read_text(encoding="utf-8") == raw_response


def test_cli_persists_llm_attempt_audit_records(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"

    class FakeClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = None
            self.last_completion_info = {
                "status": "strict_json",
                "invalid_reason": None,
                "raw_response_excerpt": '{"root_cause":"solution_incorrect"}',
                "raw_response_text": '{"root_cause":"solution_incorrect","explanation":"logic mismatch"}',
                "raw_response_sha256": "abc123",
            }

        def complete_json(self, messages):
            return {
                "root_cause": "solution_incorrect",
                "explanation": "logic mismatch",
                "observable_evidence": ["assert failed"],
                "improvement_hints": ["compare against reference"],
                "llm_signals": ["json"],
                "evidence_refs": [{"source": "tests"}],
            }

    monkeypatch.setattr("faultlens.orchestrator.LLMClient", FakeClient)

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--api-key",
        "k",
        "--base-url",
        "http://invalid.local",
        "--model",
        "m",
    ])

    assert exit_code == 0

    store = RunStore(output_dir / "run.db").open()
    try:
        attempts = store.list_llm_attempts("2")
        job = store.get_job("2")
    finally:
        store.close()

    assert len(attempts) == 1
    assert '"role": "system"' in attempts[0]["request_messages_json"]
    assert "response_text" not in attempts[0]
    assert attempts[0]["response_path"] == "llm_raw_responses/2.txt"
    assert attempts[0]["response_sha256"] == "abc123"
    assert attempts[0]["parse_mode"] == "strict_json"
    assert job["job_status"] == "finalized"


def test_run_metadata_and_report_include_job_status_distribution(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"

    class RetryableClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = "llm unavailable: HTTP Error 429: Too Many Requests"
            self.last_completion_info = {
                "status": "request_error",
                "invalid_reason": "HTTPError 429: Too Many Requests",
                "http_status": 429,
                "raw_response_excerpt": '{"error":{"message":"rate limit"}}',
                "raw_response_text": '{"error":{"message":"rate limit"}}',
                "raw_response_sha256": "abc123",
            }

        def complete_json(self, messages):
            return None

    monkeypatch.setattr("faultlens.orchestrator.LLMClient", RetryableClient)

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--api-key",
        "k",
        "--base-url",
        "http://invalid.local",
        "--model",
        "m",
        "--resume",
    ])

    assert exit_code == 0

    run_metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert run_metadata["job_status_counts"]["llm_failed_retryable"] >= 1
    assert run_metadata["pending_llm_backlog"] >= 1

    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert "# 任务状态" in report_text
    assert "llm_failed_retryable" in report_text
    assert "待处理 LLM backlog：" in report_text


def test_case_output_persists_request_error_response_body(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"
    error_body = '{"error":{"message":"rate limit exceeded","type":"rate_limit"}}'

    class FakeClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = "llm unavailable: HTTP Error 429: Too Many Requests"
            self.last_completion_info = {
                "status": "request_error",
                "invalid_reason": "HTTPError 429: Too Many Requests",
                "raw_response_excerpt": error_body,
                "raw_response_text": error_body,
                "raw_response_sha256": "abc123",
            }

        def complete_json(self, messages):
            return None

    monkeypatch.setattr("faultlens.orchestrator.LLMClient", FakeClient)

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--api-key",
        "k",
        "--base-url",
        "http://invalid.local",
        "--model",
        "m",
    ])

    assert exit_code == 0
    rows = [json.loads(line) for line in (output_dir / "case_analysis.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    failure = next(row for row in rows if row["case_id"] == "2")
    assert failure["llm_parse_mode"] == "request_error"
    assert failure["llm_parse_reason"] == "HTTPError 429: Too Many Requests"
    assert failure["llm_raw_response_path"] == "llm_raw_responses/2.txt"
    assert failure["llm_raw_response_sha256"] == "abc123"

    case_text = (output_dir / "cases" / "2.md").read_text(encoding="utf-8")
    assert "HTTPError 429: Too Many Requests" in case_text
    assert "llm_raw_responses/2.txt" in case_text

    raw_response_path = output_dir / "llm_raw_responses" / "2.txt"
    assert raw_response_path.exists()
    assert raw_response_path.read_text(encoding="utf-8") == error_body


def test_role_detection_warnings_are_persisted_into_run_metadata_and_report(tmp_path: Path):
    output_dir = tmp_path / "outputs"
    inference_path = tmp_path / "inference.jsonl"
    results_path = tmp_path / "results.jsonl"
    inference_path.write_text(
        '{"junk": 1}\n'
        '{"id":"1","content":"task","canonical_solution":"def solve():\\n    return 1","completion":"def solve():\\n    return 0"}\n',
        encoding="utf-8",
    )
    results_path.write_text('{"task_id":"1","accepted":false}\n', encoding="utf-8")

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

    run_metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")

    assert "schema outlier at line 1 in inference.jsonl" in run_metadata["input_warnings"]
    assert "schema outlier at line 1 in inference.jsonl" in report_text
