from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

from faultlens.ingest.jsonl import JsonlLoadResult, load_jsonl
from faultlens.models import InputRoleResolution


INFERENCE_REQUIRED_KEYS = {"id", "content", "canonical_solution", "completion"}
RESULTS_REQUIRED_KEYS = {"task_id", "accepted"}


def _detect_role(result: JsonlLoadResult) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not result.records:
        return "unknown", warnings

    inference_hits = 0
    results_hits = 0
    for record in result.records:
        keys = set(record.data.keys())
        if INFERENCE_REQUIRED_KEYS.issubset(keys):
            inference_hits += 1
        elif RESULTS_REQUIRED_KEYS.issubset(keys):
            results_hits += 1
        else:
            warnings.append(
                f"schema outlier at line {record.line_number} in {result.path.name}"
            )
    if inference_hits and results_hits:
        return "ambiguous", warnings
    if inference_hits:
        return "inference", warnings
    if results_hits:
        return "results", warnings
    return "unknown", warnings


def _classify_pair(left: JsonlLoadResult, right: JsonlLoadResult) -> Tuple[Path, Path, dict[str, str], list[str]]:
    left_role, left_warnings = _detect_role(left)
    right_role, right_warnings = _detect_role(right)
    detected_roles = {str(left.path): left_role, str(right.path): right_role}
    warnings = left_warnings + right_warnings

    if left_role == "inference" and right_role == "results":
        return left.path, right.path, detected_roles, warnings
    if left_role == "results" and right_role == "inference":
        return right.path, left.path, detected_roles, warnings
    raise ValueError(
        "ambiguous input roles: could not resolve inference-side/results-side files"
    )


def detect_input_roles(paths: Iterable[Path]) -> InputRoleResolution:
    ordered = [Path(p) for p in paths]
    if len(ordered) != 2:
        raise ValueError("exactly two input files are required")

    left = load_jsonl(ordered[0])
    right = load_jsonl(ordered[1])
    inference_path, results_path, detected_roles, warnings = _classify_pair(left, right)

    warnings.extend(left.warnings)
    warnings.extend(right.warnings)

    return InputRoleResolution(
        inference_path=inference_path,
        results_path=results_path,
        warnings=warnings,
        detected_roles=detected_roles,
    )
