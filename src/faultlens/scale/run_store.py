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

    def commit(self) -> None:
        connection = self._require_connection()
        connection.commit()

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

    def record_ingest_event(
        self,
        *,
        source_path: str | None,
        line_number: int | None,
        severity: str,
        event_type: str,
        message: str,
        payload_excerpt: str | None = None,
        commit: bool = True,
    ) -> None:
        connection = self._require_connection()
        connection.execute(
            """
            INSERT INTO ingest_events(
                source_path,
                line_number,
                severity,
                event_type,
                message,
                payload_excerpt,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_path,
                line_number,
                severity,
                event_type,
                message,
                payload_excerpt,
                _utcnow_iso(),
            ),
        )
        if commit:
            connection.commit()

    def list_ingest_events(self) -> list[dict[str, Any]]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT
                id,
                source_path,
                line_number,
                severity,
                event_type,
                message,
                payload_excerpt,
                created_at
            FROM ingest_events
            ORDER BY id
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

    def record_joined_case(self, case: dict[str, Any], *, commit: bool = True) -> None:
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
        if commit:
            connection.commit()

    def iter_joined_cases(self):
        connection = self._require_connection()
        cursor = connection.execute("SELECT case_json FROM joined_cases ORDER BY CAST(case_id AS TEXT)")
        for row in cursor:
            yield json.loads(row["case_json"])

    def load_joined_case(self, case_id: str) -> dict[str, Any]:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT case_json FROM joined_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        if row is None:
            raise KeyError(case_id)
        return json.loads(row["case_json"])

    def count_joined_cases(self) -> int:
        connection = self._require_connection()
        row = connection.execute("SELECT COUNT(*) AS value FROM joined_cases").fetchone()
        return int(row["value"])

    def ensure_analysis_job(self, *, case_id: str, job_status: str = "ingested", commit: bool = True) -> None:
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
        if commit:
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

    def count_jobs_by_status(self) -> dict[str, int]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT job_status, COUNT(*) AS value
            FROM analysis_jobs
            GROUP BY job_status
            ORDER BY job_status
            """
        ).fetchall()
        return {str(row["job_status"]): int(row["value"]) for row in rows}

    def update_job_after_deterministic(
        self,
        *,
        case_id: str,
        job_status: str,
        eligible_for_llm: bool,
        llm_required: bool,
        commit: bool = True,
    ) -> None:
        connection = self._require_connection()
        connection.execute(
            """
            UPDATE analysis_jobs
            SET job_status = ?,
                eligible_for_llm = ?,
                deterministic_ready = 1,
                llm_required = ?,
                updated_at = ?
            WHERE case_id = ?
            """,
            (job_status, int(eligible_for_llm), int(llm_required), _utcnow_iso(), case_id),
        )
        if commit:
            connection.commit()

    def save_deterministic_result(
        self,
        *,
        case_id: str,
        case_status: str,
        failure_gate_warnings: list[str],
        deterministic_signals: list[str],
        deterministic_findings: dict[str, Any],
        deterministic_root_cause_hint: str | None,
        analysis_version: str,
        commit: bool = True,
    ) -> None:
        connection = self._require_connection()
        now = _utcnow_iso()
        connection.execute(
            """
            INSERT OR REPLACE INTO deterministic_results(
                case_id,
                case_status,
                failure_gate_warnings_json,
                deterministic_signals_json,
                deterministic_findings_json,
                deterministic_root_cause_hint,
                runner_warnings_json,
                analysis_version,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM deterministic_results WHERE case_id = ?), ?), ?)
            """,
            (
                case_id,
                case_status,
                json.dumps(failure_gate_warnings, ensure_ascii=False),
                json.dumps(deterministic_signals, ensure_ascii=False),
                json.dumps(deterministic_findings, ensure_ascii=False),
                deterministic_root_cause_hint,
                json.dumps(deterministic_findings.get("runner_warnings", []), ensure_ascii=False),
                analysis_version,
                case_id,
                now,
                now,
            ),
        )
        if commit:
            connection.commit()

    def get_deterministic_result(self, case_id: str) -> dict[str, Any]:
        connection = self._require_connection()
        row = connection.execute(
            """
            SELECT
                case_id,
                case_status,
                failure_gate_warnings_json,
                deterministic_signals_json,
                deterministic_findings_json,
                deterministic_root_cause_hint,
                runner_warnings_json,
                analysis_version,
                created_at,
                updated_at
            FROM deterministic_results
            WHERE case_id = ?
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            raise KeyError(case_id)
        result = dict(row)
        result["failure_gate_warnings_json"] = json.loads(result["failure_gate_warnings_json"])
        result["deterministic_signals_json"] = json.loads(result["deterministic_signals_json"])
        result["deterministic_findings_json"] = json.loads(result["deterministic_findings_json"])
        result["runner_warnings_json"] = json.loads(result["runner_warnings_json"])
        return result

    def get_job(self, case_id: str) -> dict[str, Any]:
        connection = self._require_connection()
        row = connection.execute(
            """
            SELECT
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
            FROM analysis_jobs
            WHERE case_id = ?
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            raise KeyError(case_id)
        return dict(row)

    def update_job_lease(self, *, case_id: str, lease_token: str | None, lease_until: str | None) -> None:
        connection = self._require_connection()
        connection.execute(
            """
            UPDATE analysis_jobs
            SET worker_lease_token = ?,
                worker_lease_until = ?,
                updated_at = ?
            WHERE case_id = ?
            """,
            (lease_token, lease_until, _utcnow_iso(), case_id),
        )
        connection.commit()

    def mark_job_llm_running(self, *, case_id: str, lease_token: str, lease_until: str, commit: bool = True) -> None:
        connection = self._require_connection()
        connection.execute(
            """
            UPDATE analysis_jobs
            SET job_status = 'llm_running',
                attempt_count = attempt_count + 1,
                worker_lease_token = ?,
                worker_lease_until = ?,
                updated_at = ?
            WHERE case_id = ?
            """,
            (lease_token, lease_until, _utcnow_iso(), case_id),
        )
        if commit:
            connection.commit()

    def mark_job_llm_done(self, case_id: str, *, commit: bool = True) -> None:
        connection = self._require_connection()
        connection.execute(
            """
            UPDATE analysis_jobs
            SET job_status = 'llm_done',
                worker_lease_token = NULL,
                worker_lease_until = NULL,
                updated_at = ?
            WHERE case_id = ?
            """,
            (_utcnow_iso(), case_id),
        )
        if commit:
            connection.commit()

    def mark_job_llm_failed(
        self,
        *,
        case_id: str,
        retryable: bool,
        last_error: str | None,
        next_retry_at: str | None = None,
        commit: bool = True,
    ) -> None:
        connection = self._require_connection()
        connection.execute(
            """
            UPDATE analysis_jobs
            SET job_status = ?,
                next_retry_at = ?,
                last_error = ?,
                worker_lease_token = NULL,
                worker_lease_until = NULL,
                updated_at = ?
            WHERE case_id = ?
            """,
            (
                "llm_failed_retryable" if retryable else "llm_failed_terminal",
                next_retry_at,
                last_error,
                _utcnow_iso(),
                case_id,
            ),
        )
        if commit:
            connection.commit()

    def mark_job_finalized(self, case_id: str, *, commit: bool = True) -> None:
        connection = self._require_connection()
        connection.execute(
            """
            UPDATE analysis_jobs
            SET job_status = 'finalized',
                worker_lease_token = NULL,
                worker_lease_until = NULL,
                updated_at = ?
            WHERE case_id = ?
            """,
            (_utcnow_iso(), case_id),
        )
        if commit:
            connection.commit()

    def record_llm_attempt(
        self,
        *,
        case_id: str,
        attempt_index: int,
        request_messages: list[dict[str, str]],
        provider_model: str | None,
        provider_base_url: str | None,
        started_at: str,
        finished_at: str,
        outcome: str,
        parse_mode: str | None,
        parse_reason: str | None,
        response_text: str | None,
        response_sha256: str | None,
        error_type: str | None,
        error_message: str | None,
        http_status: int | None,
        is_selected: bool = True,
        commit: bool = True,
    ) -> int:
        connection = self._require_connection()
        request_messages_json = json.dumps(request_messages, ensure_ascii=False, sort_keys=True)
        request_sha256 = hashlib.sha256(request_messages_json.encode("utf-8")).hexdigest()
        latency_ms = max(
            0,
            int((datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)).total_seconds() * 1000),
        )
        cursor = connection.execute(
            """
            INSERT INTO llm_attempts(
                case_id,
                attempt_index,
                request_messages_json,
                request_sha256,
                provider_model,
                provider_base_url,
                http_status,
                started_at,
                finished_at,
                latency_ms,
                outcome,
                error_type,
                error_message,
                response_text,
                response_sha256,
                parse_mode,
                parse_reason,
                is_selected
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                attempt_index,
                request_messages_json,
                request_sha256,
                provider_model,
                provider_base_url,
                http_status,
                started_at,
                finished_at,
                latency_ms,
                outcome,
                error_type,
                error_message,
                response_text,
                response_sha256,
                parse_mode,
                parse_reason,
                int(is_selected),
            ),
        )
        if commit:
            connection.commit()
        return int(cursor.lastrowid)

    def list_llm_attempts(self, case_id: str) -> list[dict[str, Any]]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT
                id,
                case_id,
                attempt_index,
                request_messages_json,
                request_sha256,
                provider_model,
                provider_base_url,
                http_status,
                started_at,
                finished_at,
                latency_ms,
                outcome,
                error_type,
                error_message,
                response_text,
                response_sha256,
                parse_mode,
                parse_reason,
                is_selected
            FROM llm_attempts
            WHERE case_id = ?
            ORDER BY attempt_index, id
            """,
            (case_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def requeue_expired_leases(self, *, now: str) -> int:
        connection = self._require_connection()
        cursor = connection.execute(
            """
            UPDATE analysis_jobs
            SET job_status = 'llm_pending',
                worker_lease_token = NULL,
                worker_lease_until = NULL,
                updated_at = ?
            WHERE job_status = 'llm_running'
              AND worker_lease_until IS NOT NULL
              AND worker_lease_until < ?
            """,
            (now, now),
        )
        connection.commit()
        return int(cursor.rowcount)

    def requeue_retryable_jobs(self, *, now: str) -> int:
        connection = self._require_connection()
        cursor = connection.execute(
            """
            UPDATE analysis_jobs
            SET job_status = 'llm_pending',
                next_retry_at = NULL,
                updated_at = ?
            WHERE job_status = 'llm_failed_retryable'
              AND next_retry_at IS NOT NULL
              AND next_retry_at <= ?
            """,
            (now, now),
        )
        connection.commit()
        return int(cursor.rowcount)

    def expire_retryable_jobs(self, *, now: str, max_attempts: int) -> int:
        connection = self._require_connection()
        cursor = connection.execute(
            """
            UPDATE analysis_jobs
            SET job_status = 'llm_failed_terminal',
                next_retry_at = NULL,
                worker_lease_token = NULL,
                worker_lease_until = NULL,
                updated_at = ?
            WHERE job_status = 'llm_failed_retryable'
              AND attempt_count >= ?
            """,
            (now, max_attempts),
        )
        connection.commit()
        return int(cursor.rowcount)

    def save_final_result(self, result_row: dict[str, Any], *, commit: bool = True) -> None:
        connection = self._require_connection()
        now = _utcnow_iso()
        connection.execute(
            """
            INSERT OR REPLACE INTO final_results(
                case_id,
                final_result_json,
                final_decision_source,
                root_cause,
                secondary_cause,
                confidence,
                needs_human_review,
                review_reason,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM final_results WHERE case_id = ?), ?), ?)
            """,
            (
                str(result_row["case_id"]),
                json.dumps(result_row, ensure_ascii=False),
                result_row.get("final_decision_source", "deterministic_only"),
                result_row.get("root_cause"),
                result_row.get("secondary_cause"),
                result_row.get("confidence"),
                int(bool(result_row.get("needs_human_review"))),
                result_row.get("review_reason"),
                str(result_row["case_id"]),
                now,
                now,
            ),
        )
        if commit:
            connection.commit()

    def iter_final_result_rows(self):
        connection = self._require_connection()
        cursor = connection.execute(
            "SELECT final_result_json FROM final_results ORDER BY CAST(case_id AS TEXT)"
        )
        for row in cursor:
            yield json.loads(row["final_result_json"])

    def count_final_results(self) -> int:
        connection = self._require_connection()
        row = connection.execute("SELECT COUNT(*) AS value FROM final_results").fetchone()
        return int(row["value"])

    def has_final_result(self, case_id: str) -> bool:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT 1 FROM final_results WHERE case_id = ? LIMIT 1",
            (case_id,),
        ).fetchone()
        return row is not None

    def iter_llm_attempt_rows(self):
        connection = self._require_connection()
        cursor = connection.execute(
            """
            SELECT
                case_id,
                attempt_index,
                error_message,
                response_text,
                parse_mode,
                parse_reason
            FROM llm_attempts
            ORDER BY id
            """
        )
        for row in cursor:
            yield dict(row)

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("run store is not open")
        return self.connection
