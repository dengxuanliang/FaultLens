from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, Iterator


class CheckpointStore:
    def __init__(self, path: Path, *, enabled: bool) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self.connection: sqlite3.Connection | None = None

    def open(self) -> "CheckpointStore":
        if not self.enabled:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS processed_results (case_id TEXT PRIMARY KEY, result_json TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)"
        )
        self.connection.commit()
        return self

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def has_case(self, case_id: str) -> bool:
        if not self.enabled or self.connection is None:
            return False
        row = self.connection.execute(
            "SELECT 1 FROM processed_results WHERE case_id = ? LIMIT 1", (str(case_id),)
        ).fetchone()
        return row is not None

    def store_result(self, case_id: str, result_row: Dict[str, Any]) -> None:
        if not self.enabled or self.connection is None:
            return
        self.connection.execute(
            "INSERT OR REPLACE INTO processed_results(case_id, result_json) VALUES (?, ?)",
            (str(case_id), json.dumps(result_row, ensure_ascii=False)),
        )
        self.connection.commit()

    def iter_result_rows(self) -> Iterator[Dict[str, Any]]:
        if not self.enabled or self.connection is None:
            return iter(())
        cursor = self.connection.execute(
            "SELECT result_json FROM processed_results ORDER BY CAST(case_id AS TEXT)"
        )
        return (json.loads(row[0]) for row in cursor)

    def load_metadata(self, key: str, default: Any) -> Any:
        if not self.enabled or self.connection is None:
            return default
        row = self.connection.execute("SELECT value_json FROM metadata WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def save_metadata(self, key: str, value: Any) -> None:
        if not self.enabled or self.connection is None:
            return
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value_json) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self.connection.commit()
