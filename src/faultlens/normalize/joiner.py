from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from tempfile import NamedTemporaryFile
from typing import Any, Dict, Iterator, List, Optional

from faultlens.ingest.jsonl import JsonlRecord, iter_jsonl_records



def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)



def _extract_metadata_tags(result_record: Dict[str, Any]) -> Dict[str, Any]:
    keys = ["natural_language", "programming_language", "category", "difficulty"]
    return {key: result_record.get(key) for key in keys if result_record.get(key) is not None}



def _derive_slice_fields(inference_labels: Dict[str, Any], results_tags: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
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



def _build_joined_case(case_id: str, inference_record: JsonlRecord, results_record: JsonlRecord) -> Dict[str, Any]:
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
    return list(join_records_iter(inference_path, results_path))



def join_records_iter(inference_path: Path, results_path: Path) -> Iterator[Dict[str, Any]]:
    with NamedTemporaryFile(prefix="faultlens-join-", suffix=".sqlite3") as handle:
        connection = sqlite3.connect(handle.name)
        try:
            connection.execute("CREATE TABLE records (side TEXT NOT NULL, join_key TEXT NOT NULL, line_number INTEGER NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(side, join_key))")
            all_loader_warnings: List[str] = []
            inference_dups = _stream_into_index(connection, Path(inference_path), "inference", "id", all_loader_warnings)
            results_dups = _stream_into_index(connection, Path(results_path), "results", "task_id", all_loader_warnings)

            query = """
                SELECT keys.join_key,
                       inf.line_number, inf.payload_json,
                       res.line_number, res.payload_json
                FROM (
                    SELECT join_key FROM records WHERE side = 'inference'
                    UNION
                    SELECT join_key FROM records WHERE side = 'results'
                ) AS keys
                LEFT JOIN records AS inf ON inf.side = 'inference' AND inf.join_key = keys.join_key
                LEFT JOIN records AS res ON res.side = 'results' AND res.join_key = keys.join_key
                ORDER BY LENGTH(keys.join_key), keys.join_key
            """
            for join_key, inf_line, inf_payload, res_line, res_payload in connection.execute(query):
                if inf_payload is None or res_payload is None:
                    case = _build_join_issue_case(str(join_key), f"missing pair for key {join_key}")
                elif str(join_key) in inference_dups or str(join_key) in results_dups:
                    case = _build_join_issue_case(str(join_key), f"duplicate join key {join_key}")
                else:
                    case = _build_joined_case(
                        str(join_key),
                        JsonlRecord(line_number=int(inf_line), data=json.loads(inf_payload)),
                        JsonlRecord(line_number=int(res_line), data=json.loads(res_payload)),
                    )
                if all_loader_warnings:
                    case["normalization"]["warnings"].extend(all_loader_warnings)
                yield case
        finally:
            connection.close()



def _stream_into_index(connection: sqlite3.Connection, path: Path, side: str, key_name: str, warnings: List[str]) -> set[str]:
    duplicates: set[str] = set()
    for item in iter_jsonl_records(path):
        if isinstance(item, str):
            warnings.append(item)
            continue
        key = _stringify(item.data.get(key_name))
        if key is None:
            warnings.append(f"{side} missing {key_name} at line {item.line_number}")
            continue
        try:
            connection.execute(
                "INSERT INTO records(side, join_key, line_number, payload_json) VALUES (?, ?, ?, ?)",
                (side, key, item.line_number, json.dumps(item.data, ensure_ascii=False)),
            )
        except sqlite3.IntegrityError:
            duplicates.add(key)
            warnings.append(f"duplicate {side} key {key}")
    connection.commit()
    return duplicates
