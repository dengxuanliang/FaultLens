from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple


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
    for item in iter_jsonl_records(path):
        if isinstance(item, str):
            result.warnings.append(item)
        else:
            result.records.append(item)
    return result



def sample_jsonl(path: Path, *, limit: int = 50) -> JsonlLoadResult:
    result = JsonlLoadResult(path=Path(path))
    for item in iter_jsonl_records(path):
        if isinstance(item, str):
            result.warnings.append(item)
            continue
        result.records.append(item)
        if len(result.records) >= limit:
            break
    return result



def iter_jsonl_records(path: Path) -> Iterator[JsonlRecord | str]:
    normalized = Path(path)
    if not normalized.exists():
        yield f"file not found: {normalized}"
        return

    with normalized.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                yield f"empty line {line_number} in {normalized.name}"
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                yield f"bad json at line {line_number} in {normalized.name}"
                continue
            if not isinstance(parsed, dict):
                yield f"non-object json at line {line_number} in {normalized.name}"
                continue
            yield JsonlRecord(line_number=line_number, data=parsed)
