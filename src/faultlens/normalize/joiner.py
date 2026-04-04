from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from tempfile import NamedTemporaryFile
from typing import Any, Dict, Iterator, List, Optional

from faultlens.ingest.jsonl import JsonlRecord, JsonlScanObserver, iter_jsonl_records
from faultlens.scale.run_store import RunStore



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



def join_records_iter(
    inference_path: Path,
    results_path: Path,
    *,
    store: RunStore | None = None,
) -> Iterator[Dict[str, Any]]:
    with NamedTemporaryFile(prefix="faultlens-join-", suffix=".sqlite3") as handle:
        connection = sqlite3.connect(handle.name)
        try:
            connection.execute("CREATE TABLE records (side TEXT NOT NULL, join_key TEXT NOT NULL, line_number INTEGER NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(side, join_key))")
            inference_dups, _ = _stream_into_index(connection, Path(inference_path), "inference", "id", store)
            results_dups, _ = _stream_into_index(connection, Path(results_path), "results", "task_id", store)

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
                    reason = f"missing pair for key {join_key}"
                    case = _build_join_issue_case(str(join_key), reason)
                    _record_ingest_event(
                        store,
                        source_path=None,
                        line_number=None,
                        severity="warning",
                        event_type="missing_pair",
                        message=reason,
                        payload_excerpt=str(join_key),
                    )
                elif str(join_key) in inference_dups or str(join_key) in results_dups:
                    reason = f"duplicate join key {join_key}"
                    case = _build_join_issue_case(str(join_key), reason)
                    _record_ingest_event(
                        store,
                        source_path=None,
                        line_number=None,
                        severity="warning",
                        event_type="duplicate_join_key",
                        message=reason,
                        payload_excerpt=str(join_key),
                    )
                else:
                    case = _build_joined_case(
                        str(join_key),
                        JsonlRecord(line_number=int(inf_line), data=json.loads(inf_payload)),
                        JsonlRecord(line_number=int(res_line), data=json.loads(res_payload)),
                    )
                yield case
        finally:
            connection.close()


def build_ingest_snapshot(store: RunStore, inference_path: Path, results_path: Path) -> None:
    for case in join_records_iter(inference_path, results_path, store=store):
        store.record_joined_case(case, commit=False)
        store.ensure_analysis_job(case_id=str(case.get("case_id")), job_status="ingested", commit=False)
    store.commit()


def build_ingest_snapshot_with_manifest(
    store: RunStore,
    inference_path: Path,
    results_path: Path,
    *,
    input_metadata: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    path_metadata = {item["path"]: dict(item) for item in input_metadata}
    snapshots: dict[str, dict[str, Any]] = {}
    with NamedTemporaryFile(prefix="faultlens-join-", suffix=".sqlite3") as handle:
        connection = sqlite3.connect(handle.name)
        try:
            connection.execute("CREATE TABLE records (side TEXT NOT NULL, join_key TEXT NOT NULL, line_number INTEGER NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(side, join_key))")
            inference_dups, inference_scan = _stream_into_index(connection, Path(inference_path), "inference", "id", store)
            results_dups, results_scan = _stream_into_index(connection, Path(results_path), "results", "task_id", store)
            snapshots[str(inference_path)] = {**path_metadata[str(inference_path)], **inference_scan}
            snapshots[str(results_path)] = {**path_metadata[str(results_path)], **results_scan}

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
                    reason = f"missing pair for key {join_key}"
                    case = _build_join_issue_case(str(join_key), reason)
                    _record_ingest_event(
                        store,
                        source_path=None,
                        line_number=None,
                        severity="warning",
                        event_type="missing_pair",
                        message=reason,
                        payload_excerpt=str(join_key),
                    )
                elif str(join_key) in inference_dups or str(join_key) in results_dups:
                    reason = f"duplicate join key {join_key}"
                    case = _build_join_issue_case(str(join_key), reason)
                    _record_ingest_event(
                        store,
                        source_path=None,
                        line_number=None,
                        severity="warning",
                        event_type="duplicate_join_key",
                        message=reason,
                        payload_excerpt=str(join_key),
                    )
                else:
                    case = _build_joined_case(
                        str(join_key),
                        JsonlRecord(line_number=int(inf_line), data=json.loads(inf_payload)),
                        JsonlRecord(line_number=int(res_line), data=json.loads(res_payload)),
                    )
                store.record_joined_case(case, commit=False)
                store.ensure_analysis_job(case_id=str(case.get("case_id")), job_status="ingested", commit=False)
        finally:
            connection.close()
    store.commit()
    return [snapshots[item["path"]] for item in sorted(input_metadata, key=lambda row: row["declared_order"])]


def iter_joined_cases_from_store(store: RunStore) -> Iterator[Dict[str, Any]]:
    yield from store.iter_joined_cases()



def _stream_into_index(
    connection: sqlite3.Connection,
    path: Path,
    side: str,
    key_name: str,
    store: RunStore | None,
) -> tuple[set[str], dict[str, Any]]:
    duplicates: set[str] = set()
    observer = JsonlScanObserver()
    for item in iter_jsonl_records(path, observer=observer):
        if isinstance(item, str):
            _record_loader_warning(store, path, side, item)
            continue
        key = _stringify(item.data.get(key_name))
        if key is None:
            _record_ingest_event(
                store,
                source_path=str(path),
                line_number=item.line_number,
                severity="warning",
                event_type="missing_join_key",
                message=f"{side} missing {key_name} at line {item.line_number}",
                payload_excerpt=json.dumps(item.data, ensure_ascii=False)[:400],
            )
            continue
        try:
            connection.execute(
                "INSERT INTO records(side, join_key, line_number, payload_json) VALUES (?, ?, ?, ?)",
                (side, key, item.line_number, json.dumps(item.data, ensure_ascii=False)),
            )
        except sqlite3.IntegrityError:
            duplicates.add(key)
            _record_ingest_event(
                store,
                source_path=str(path),
                line_number=item.line_number,
                severity="warning",
                event_type="duplicate_join_key",
                message=f"duplicate {side} key {key}",
                payload_excerpt=str(key),
            )
    connection.commit()
    return duplicates, {
        "sha256": observer.sha256,
        "sample_record_count": observer.sample_record_count,
    }


def _record_loader_warning(store: RunStore | None, path: Path, side: str, warning: str) -> None:
    _record_ingest_event(
        store,
        source_path=str(path),
        line_number=_extract_line_number(warning),
        severity="warning",
        event_type=_classify_warning_event(warning),
        message=warning,
        payload_excerpt=side,
    )


def _record_ingest_event(
    store: RunStore | None,
    *,
    source_path: str | None,
    line_number: int | None,
    severity: str,
    event_type: str,
    message: str,
    payload_excerpt: str | None,
) -> None:
    if store is None:
        return
    store.record_ingest_event(
        source_path=source_path,
        line_number=line_number,
        severity=severity,
        event_type=event_type,
        message=message,
        payload_excerpt=payload_excerpt,
        commit=False,
    )


def _extract_line_number(message: str) -> int | None:
    if "line " not in message:
        return None
    suffix = message.split("line ", 1)[1].split(" ", 1)[0]
    return int(suffix) if suffix.isdigit() else None


def _classify_warning_event(message: str) -> str:
    if message.startswith("empty line "):
        return "empty_line"
    if message.startswith("bad json at line "):
        return "bad_json"
    if message.startswith("non-object json at line "):
        return "non_object_json"
    return "schema_outlier"
