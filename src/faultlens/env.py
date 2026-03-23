from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping, Optional
import os


def load_dotenv(env_path: Optional[Path]) -> Dict[str, str]:
    if env_path is None:
        return {}
    path = Path(env_path)
    if not path.exists():
        return {}
    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def merge_env(dotenv_values: Mapping[str, str]) -> Dict[str, str]:
    merged = dict(dotenv_values)
    merged.update(os.environ)
    return merged
