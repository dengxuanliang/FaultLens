from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import uuid
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

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("run store is not open")
        return self.connection
