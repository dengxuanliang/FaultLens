from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

from faultlens.ingest.jsonl import JsonlLoadResult, load_jsonl
from faultlens.models import InputRoleResolution


INFERENCE_REQUIRED_KEYS = {"id", "content", "canonical_solution", "completion"}
RESULTS_REQUIRED_KEYS = {"task_id", "accepted"}


def _detect_role(result: JsonlLoadResult) -> str:
    if not result.records:
        return "unknown"
    keys = set(result.records[0].data.keys())
    is_inference = INFERENCE_REQUIRED_KEYS.issubset(keys)
    is_results = RESULTS_REQUIRED_KEYS.issubset(keys)
    if is_inference and is_results:
        return "ambiguous"
    if is_inference:
        return "inference"
    if is_results:
        return "results"
    return "unknown"


def _classify_pair(left: JsonlLoadResult, right: JsonlLoadResult) -> Tuple[Path, Path]:
    left_role = _detect_role(left)
    right_role = _detect_role(right)

    if left_role == "inference" and right_role == "results":
        return left.path, right.path
    if left_role == "results" and right_role == "inference":
        return right.path, left.path
    raise ValueError(
        "ambiguous input roles: could not resolve inference-side/results-side files"
    )


def detect_input_roles(paths: Iterable[Path]) -> InputRoleResolution:
    ordered = [Path(p) for p in paths]
    if len(ordered) != 2:
        raise ValueError("exactly two input files are required")

    left = load_jsonl(ordered[0])
    right = load_jsonl(ordered[1])
    inference_path, results_path = _classify_pair(left, right)

    warnings = []
    warnings.extend(left.warnings)
    warnings.extend(right.warnings)

    return InputRoleResolution(
        inference_path=inference_path, results_path=results_path, warnings=warnings
    )
