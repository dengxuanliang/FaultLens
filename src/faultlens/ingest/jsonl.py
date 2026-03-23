from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class JsonlRecord:
    line_number: int
    data: Dict[str, Any]


@dataclass
class JsonlLoadResult:
    path: Path
    records: List[JsonlRecord] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def load_jsonl(path: Path) -> JsonlLoadResult:
    result = JsonlLoadResult(path=Path(path))
    if not result.path.exists():
        result.warnings.append(f"file not found: {result.path}")
        return result

    for line_number, raw in enumerate(
        result.path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            result.warnings.append(f"empty line {line_number} in {result.path.name}")
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            result.warnings.append(
                f"bad json at line {line_number} in {result.path.name}"
            )
            continue
        if not isinstance(parsed, dict):
            result.warnings.append(
                f"non-object json at line {line_number} in {result.path.name}"
            )
            continue
        result.records.append(JsonlRecord(line_number=line_number, data=parsed))
    return result
