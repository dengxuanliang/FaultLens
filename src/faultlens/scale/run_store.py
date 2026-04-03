from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import uuid
import hashlib
from typing import Any

from faultlens.scale.schema import SCHEMA_VERSION, initialize_schema


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class RunStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.connection: sqlite3.Connection | None = None

    def open(self) -> "RunStore":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        initialize_schema(self.connection)
        self.connection.commit()
        return self

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def list_tables(self) -> set[str]:
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {str(row["name"]) for row in rows}

    def has_run_metadata(self) -> bool:
        connection = self._require_connection()
        row = connection.execute("SELECT 1 FROM run_metadata LIMIT 1").fetchone()
        return row is not None

    def initialize_run_metadata(
        self,
        *,
        analysis_version: str,
        prompt_version: str,
        settings: dict[str, Any],
        faultlens_version: str | None = None,
        git_commit: str | None = None,
    ) -> dict[str, Any]:
        connection = self._require_connection()
        payload = {
            "run_id": str(uuid.uuid4()),
            "created_at": _utcnow_iso(),
            "faultlens_version": faultlens_version,
            "schema_version": SCHEMA_VERSION,
            "analysis_version": analysis_version,
            "prompt_version": prompt_version,
            "settings_json": json.dumps(settings, ensure_ascii=False, sort_keys=True),
            "git_commit": git_commit,
        }
        connection.execute("DELETE FROM run_metadata")
        connection.execute(
            """
            INSERT INTO run_metadata(
                run_id,
                created_at,
                faultlens_version,
                schema_version,
                analysis_version,
                prompt_version,
                settings_json,
                git_commit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["run_id"],
                payload["created_at"],
                payload["faultlens_version"],
                payload["schema_version"],
                payload["analysis_version"],
                payload["prompt_version"],
                payload["settings_json"],
                payload["git_commit"],
            ),
        )
        connection.commit()
        return self.load_run_metadata()

    def load_run_metadata(self) -> dict[str, Any]:
        connection = self._require_connection()
        row = connection.execute(
            """
            SELECT
                run_id,
                created_at,
                faultlens_version,
                schema_version,
                analysis_version,
                prompt_version,
                settings_json,
                git_commit
            FROM run_metadata
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            raise ValueError("run metadata is not initialized")
        result = dict(row)
        result["settings_json"] = json.loads(result["settings_json"])
        return result

    def record_input_file(
        self,
        *,
        path: str,
        declared_order: int,
        detected_role: str,
        size_bytes: int,
        mtime_epoch: float,
        sha256: str,
        sample_record_count: int,
    ) -> None:
        connection = self._require_connection()
        connection.execute(
            """
            INSERT OR REPLACE INTO input_files(
                path,
                declared_order,
                detected_role,
                size_bytes,
                mtime_epoch,
                sha256,
                sample_record_count,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                path,
                declared_order,
                detected_role,
                size_bytes,
                mtime_epoch,
                sha256,
                sample_record_count,
                _utcnow_iso(),
            ),
        )
        connection.commit()

    def replace_input_files(self, files: list[dict[str, Any]]) -> None:
        connection = self._require_connection()
        connection.execute("DELETE FROM input_files")
        for item in files:
            connection.execute(
                """
                INSERT INTO input_files(
                    path,
                    declared_order,
                    detected_role,
                    size_bytes,
                    mtime_epoch,
                    sha256,
                    sample_record_count,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["path"],
                    item["declared_order"],
                    item["detected_role"],
                    item["size_bytes"],
                    item["mtime_epoch"],
                    item["sha256"],
                    item["sample_record_count"],
                    _utcnow_iso(),
                ),
            )
        connection.commit()

    def load_input_files(self) -> list[dict[str, Any]]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT
                path,
                declared_order,
                detected_role,
                size_bytes,
                mtime_epoch,
                sha256,
                sample_record_count,
                created_at
            FROM input_files
            ORDER BY declared_order, path
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def assert_resume_safe(
        self,
        *,
        current_inputs: list[dict[str, Any]],
        analysis_version: str,
        prompt_version: str,
    ) -> None:
        metadata = self.load_run_metadata()
        if metadata["analysis_version"] != analysis_version:
            raise ValueError("analysis version mismatch; resume is not safe")
        if metadata["prompt_version"] != prompt_version:
            raise ValueError("prompt version mismatch; resume is not safe")
        stored_inputs = self.load_input_files()
        comparable_keys = [
            "path",
            "declared_order",
            "detected_role",
            "size_bytes",
            "mtime_epoch",
            "sha256",
            "sample_record_count",
        ]
        normalized_current = [{key: item[key] for key in comparable_keys} for item in current_inputs]
        normalized_stored = [{key: item[key] for key in comparable_keys} for item in stored_inputs]
        if normalized_current != normalized_stored:
            raise ValueError("input manifest mismatch; resume is not safe")

    def record_joined_case(self, case: dict[str, Any]) -> None:
        connection = self._require_connection()
        now = _utcnow_iso()
        source = case.get("source", {}) or {}
        raw = case.get("raw", {}) or {}
        normalization = case.get("normalization", {}) or {}
        case_json = json.dumps(case, ensure_ascii=False, sort_keys=True)
        connection.execute(
            """
            INSERT OR REPLACE INTO joined_cases(
                case_id,
                join_status,
                inference_line_number,
                results_line_number,
                input_role_detection,
                case_json,
                inference_payload_json,
                results_payload_json,
                normalization_warnings_json,
                normalization_errors_json,
                join_anomaly_flags_json,
                content_sha256,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(case.get("case_id")),
                case.get("join_status", "unknown"),
                source.get("inference_line_number"),
                source.get("results_line_number"),
                source.get("input_role_detection"),
                case_json,
                json.dumps(raw.get("inference_record"), ensure_ascii=False, sort_keys=True),
                json.dumps(raw.get("results_record"), ensure_ascii=False, sort_keys=True),
                json.dumps(normalization.get("warnings", []), ensure_ascii=False),
                json.dumps(normalization.get("errors", []), ensure_ascii=False),
                json.dumps(case.get("join_anomaly_flags", []), ensure_ascii=False),
                hashlib.sha256(case_json.encode("utf-8")).hexdigest(),
                now,
                now,
            ),
        )
        connection.commit()

    def iter_joined_cases(self):
        connection = self._require_connection()
        cursor = connection.execute("SELECT case_json FROM joined_cases ORDER BY CAST(case_id AS TEXT)")
        for row in cursor:
            yield json.loads(row["case_json"])

    def count_joined_cases(self) -> int:
        connection = self._require_connection()
        row = connection.execute("SELECT COUNT(*) AS value FROM joined_cases").fetchone()
        return int(row["value"])

    def ensure_analysis_job(self, *, case_id: str, job_status: str = "ingested") -> None:
        connection = self._require_connection()
        now = _utcnow_iso()
        connection.execute(
            """
            INSERT OR REPLACE INTO analysis_jobs(
                case_id,
                job_status,
                eligible_for_llm,
                deterministic_ready,
                llm_required,
                attempt_count,
                next_retry_at,
                worker_lease_token,
                worker_lease_until,
                last_error,
                created_at,
                updated_at
            ) VALUES (
                ?,
                ?,
                COALESCE((SELECT eligible_for_llm FROM analysis_jobs WHERE case_id = ?), NULL),
                COALESCE((SELECT deterministic_ready FROM analysis_jobs WHERE case_id = ?), NULL),
                COALESCE((SELECT llm_required FROM analysis_jobs WHERE case_id = ?), NULL),
                COALESCE((SELECT attempt_count FROM analysis_jobs WHERE case_id = ?), 0),
                COALESCE((SELECT next_retry_at FROM analysis_jobs WHERE case_id = ?), NULL),
                COALESCE((SELECT worker_lease_token FROM analysis_jobs WHERE case_id = ?), NULL),
                COALESCE((SELECT worker_lease_until FROM analysis_jobs WHERE case_id = ?), NULL),
                COALESCE((SELECT last_error FROM analysis_jobs WHERE case_id = ?), NULL),
                COALESCE((SELECT created_at FROM analysis_jobs WHERE case_id = ?), ?),
                ?
            )
            """,
            (case_id, job_status, case_id, case_id, case_id, case_id, case_id, case_id, case_id, case_id, case_id, now, now),
        )
        connection.commit()

    def count_jobs(self, status: str | None = None) -> int:
        connection = self._require_connection()
        if status is None:
            row = connection.execute("SELECT COUNT(*) AS value FROM analysis_jobs").fetchone()
        else:
            row = connection.execute(
                "SELECT COUNT(*) AS value FROM analysis_jobs WHERE job_status = ?",
                (status,),
            ).fetchone()
        return int(row["value"])

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("run store is not open")
        return self.connection
