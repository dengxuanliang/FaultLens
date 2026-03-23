from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from faultlens.ingest.jsonl import JsonlRecord, load_jsonl


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _index_by_key(
    records: List[JsonlRecord], key_name: str, side: str
) -> tuple[Dict[str, JsonlRecord], Dict[str, int], List[str]]:
    index: Dict[str, JsonlRecord] = {}
    duplicate_counts: Dict[str, int] = {}
    warnings: List[str] = []
    for record in records:
        key = _stringify(record.data.get(key_name))
        if key is None:
            warnings.append(f"{side} missing {key_name} at line {record.line_number}")
            continue
        if key in index:
            duplicate_counts[key] = duplicate_counts.get(key, 1) + 1
            warnings.append(f"duplicate {side} key {key}")
            continue
        index[key] = record
    return index, duplicate_counts, warnings


def _extract_metadata_tags(result_record: Dict[str, Any]) -> Dict[str, Any]:
    keys = ["natural_language", "programming_language", "category", "difficulty"]
    return {key: result_record.get(key) for key in keys if result_record.get(key) is not None}


def _derive_slice_fields(
    inference_labels: Dict[str, Any], results_tags: Dict[str, Any]
) -> tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    slice_fields: Dict[str, Any] = {}

    preferred_keys = [
        "programming_language",
        "execution_language",
        "category",
        "difficulty",
        "fewshot",
        "locale",
        "natural_language",
    ]
    for key in preferred_keys:
        inf = inference_labels.get(key)
        res = results_tags.get(key)
        if inf is not None:
            slice_fields[key] = inf
        elif res is not None:
            slice_fields[key] = res
        if inf is not None and res is not None and inf != res:
            warnings.append(f"metadata conflict on {key}: inference={inf}, results={res}")
    return slice_fields, warnings


def _build_join_issue_case(case_id: str, reason: str) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "join_status": "error",
        "case_status": "join_issue",
        "raw": {"inference_record": None, "results_record": None},
        "source": {
            "inference_id_raw": None,
            "results_task_id_raw": None,
            "inference_line_number": None,
            "results_line_number": None,
            "input_role_detection": "unresolved",
        },
        "task": {"content_text": None},
        "reference": {"canonical_code_text": None, "test_code_text": None},
        "completion": {"raw_text": "", "code_blocks": [], "primary_code_text": ""},
        "evaluation": {"accepted": None, "pass_metrics": {}, "results_tags": {}},
        "metadata": {"inference_labels": {}, "results_tags": {}, "slice_fields": {}},
        "normalization": {"warnings": [reason], "errors": [reason]},
        "join_anomaly_flags": [reason],
        "deterministic_signals": [],
    }


def _build_joined_case(
    case_id: str, inference_record: JsonlRecord, results_record: JsonlRecord
) -> Dict[str, Any]:
    inference_data = inference_record.data
    results_data = results_record.data
    inference_labels = inference_data.get("labels") or {}
    results_tags = _extract_metadata_tags(results_data)
    slice_fields, metadata_warnings = _derive_slice_fields(inference_labels, results_tags)
    pass_metrics = {
        "passed_at_1": results_data.get("passed_at_1"),
        "pass_at_k": results_data.get("pass_at_k"),
        "all_k_correct": results_data.get("all_k_correct"),
        "n": results_data.get("n"),
    }

    return {
        "case_id": case_id,
        "join_status": "ok",
        "case_status": "unknown",
        "raw": {
            "inference_record": inference_data,
            "results_record": results_data,
        },
        "source": {
            "inference_id_raw": inference_data.get("id"),
            "results_task_id_raw": results_data.get("task_id"),
            "inference_line_number": inference_record.line_number,
            "results_line_number": results_record.line_number,
            "input_role_detection": "schema-based",
        },
        "task": {"content_text": inference_data.get("content")},
        "reference": {
            "canonical_code_text": inference_data.get("canonical_solution"),
            "test_code_text": (inference_data.get("test") or {}).get("code"),
        },
        "completion": {
            "raw_text": inference_data.get("completion") or "",
            "code_blocks": [],
            "primary_code_text": "",
        },
        "evaluation": {
            "accepted": results_data.get("accepted"),
            "pass_metrics": pass_metrics,
            "results_tags": results_tags,
        },
        "metadata": {
            "inference_labels": inference_labels,
            "results_tags": results_tags,
            "slice_fields": slice_fields,
        },
        "normalization": {"warnings": metadata_warnings.copy(), "errors": []},
        "join_anomaly_flags": [],
        "deterministic_signals": ["metadata_conflict"] if metadata_warnings else [],
    }


def join_records(inference_path: Path, results_path: Path) -> List[Dict[str, Any]]:
    inference_data = load_jsonl(Path(inference_path))
    results_data = load_jsonl(Path(results_path))

    inference_index, inference_dups, inference_warnings = _index_by_key(
        inference_data.records, "id", "inference"
    )
    results_index, results_dups, results_warnings = _index_by_key(
        results_data.records, "task_id", "results"
    )
    keys = set(inference_index.keys()) | set(results_index.keys())

    joined: List[Dict[str, Any]] = []
    for key in sorted(keys, key=lambda value: (len(value), value)):
        inf = inference_index.get(key)
        res = results_index.get(key)
        if inf is None or res is None:
            joined.append(_build_join_issue_case(key, f"missing pair for key {key}"))
            continue
        if key in inference_dups or key in results_dups:
            joined.append(_build_join_issue_case(key, f"duplicate join key {key}"))
            continue
        joined.append(_build_joined_case(key, inf, res))

    # Keep bad-line warnings visible by attaching them to each case.
    all_loader_warnings = inference_data.warnings + results_data.warnings
    all_loader_warnings += inference_warnings + results_warnings
    if all_loader_warnings:
        for case in joined:
            case["normalization"]["warnings"].extend(all_loader_warnings)
    return joined
