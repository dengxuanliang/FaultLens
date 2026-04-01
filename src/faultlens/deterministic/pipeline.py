from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List

from faultlens.deterministic.analyzers.code_extractor import extract_code_blocks
from faultlens.deterministic.analyzers.diffing import summarize_canonical_diff
from faultlens.deterministic.analyzers.harness import analyze_harness_alignment
from faultlens.deterministic.analyzers.language import infer_language
from faultlens.deterministic.runners.registry import RunnerRegistry, build_runner_registry
from faultlens.deterministic.signals import normalize_signals



def analyze_cases_deterministically(cases: List[Dict[str, Any]], execution_timeout: int = 10) -> List[Dict[str, Any]]:
    registry = build_runner_registry()
    return [analyze_case_deterministically(case, execution_timeout=execution_timeout, registry=registry) for case in cases]



def analyze_case_deterministically(case: Dict[str, Any], execution_timeout: int = 10, registry: RunnerRegistry | None = None) -> Dict[str, Any]:
    registry = registry or build_runner_registry()
    record = deepcopy(case)
    completion_raw = record.get("completion", {}).get("raw_text", "")
    extracted = extract_code_blocks(completion_raw)
    record.setdefault("completion", {})["code_blocks"] = list(extracted.code_blocks)
    record["completion"]["primary_code_text"] = extracted.primary_code_text or ""
    record["completion"]["explanation_text"] = extracted.explanation_text
    record["completion"]["parse_status"] = extracted.parse_status

    language = infer_language(
        inference_labels=record.get("metadata", {}).get("inference_labels"),
        results_tags=record.get("metadata", {}).get("results_tags"),
        fence_language=extracted.fence_languages[0] if extracted.fence_languages else None,
        completion_code=extracted.primary_code_text,
    )
    record["language"] = {
        "primary_language": language.primary,
        "candidates": language.candidates,
        "source": language.source,
    }

    diff_summary = summarize_canonical_diff(record.get("reference", {}).get("canonical_code_text"), extracted.primary_code_text)
    harness_summary = analyze_harness_alignment(
        test_code=record.get("reference", {}).get("test_code_text"),
        completion_code=extracted.primary_code_text,
        language=language.primary,
        accepted=record.get("evaluation", {}).get("accepted"),
        pass_metrics=record.get("evaluation", {}).get("pass_metrics"),
    )

    findings: Dict[str, Any] = {
        "code_extraction_status": extracted.parse_status,
        "primary_language": language.primary,
        "language_source": language.source,
        "parse_status": harness_summary.get("parse_status", extracted.parse_status),
        "parse_error_excerpt": harness_summary.get("parse_error_excerpt"),
        "signature_check_status": harness_summary.get("signature_check_status"),
        "entrypoint_check_status": harness_summary.get("entrypoint_check_status"),
        "api_check_status": harness_summary.get("api_check_status"),
        "canonical_diff_summary": diff_summary.get("summary"),
        "test_harness_alignment_summary": harness_summary.get("summary"),
        "compile_status": "not_run",
        "test_status": "not_run",
        "runtime_error_excerpt": None,
        "failing_assert_excerpt": None,
        "exit_code": None,
        "completion_code": extracted.primary_code_text,
    }

    signals = list(record.get("deterministic_signals", []))
    signals.extend(harness_summary.get("signals", []))
    if not extracted.primary_code_text:
        signals.append("missing_code")

    if record.get("case_status") == "attributable_failure" and extracted.primary_code_text and language.primary:
        runner = registry.for_language(language.primary)
        try:
            runner_result = runner.run(extracted.primary_code_text, record.get("reference", {}).get("test_code_text") or "", execution_timeout)
        except ValueError:
            runner_result = None
        if runner_result is not None:
            findings.update(
                {
                    "compile_status": runner_result.compile_status,
                    "test_status": runner_result.test_status,
                    "runtime_error_excerpt": runner_result.stderr_excerpt or None,
                    "failing_assert_excerpt": runner_result.stderr_excerpt or runner_result.stdout_excerpt or None,
                    "exit_code": runner_result.exit_code,
                    "stdout_excerpt": runner_result.stdout_excerpt,
                    "stderr_excerpt": runner_result.stderr_excerpt,
                    "runner_warnings": runner_result.warnings,
                }
            )
            if runner_result.compile_status == "failed":
                signals.append("compile_error")
            if runner_result.test_status == "failed":
                signals.append("test_failure")
                if not runner_result.stderr_excerpt or "assert" in runner_result.stderr_excerpt.lower():
                    signals.append("logic_mismatch")
            if runner_result.test_status == "timeout" or runner_result.timed_out:
                signals.append("timeout")
            if runner_result.test_status == "failed" and runner_result.stderr_excerpt and "assert" not in runner_result.stderr_excerpt.lower():
                signals.append("runtime_error")

    normalized_signals = normalize_signals(signals)
    record["deterministic_signals"] = normalized_signals
    record["deterministic_findings"] = findings
    record["deterministic_root_cause_hint"] = _suggest_root_cause(normalized_signals)
    return record



def _suggest_root_cause(signals: List[str]) -> str:
    signal_set = set(signals)
    if "suspicious_eval_mismatch" in signal_set:
        return "possible_evaluation_mismatch"
    if signal_set & {"missing_code", "code_extraction_failed"}:
        return "incomplete_or_truncated_solution"
    if signal_set & {"signature_mismatch", "entrypoint_mismatch", "api_mismatch"}:
        return "contract_or_interface_violation"
    if signal_set & {"compile_error", "runtime_error"}:
        return "implementation_bug"
    if signal_set & {"test_failure", "logic_mismatch"}:
        return "solution_incorrect"
    return "insufficient_evidence"
