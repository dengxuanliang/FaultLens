from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping, Optional
import os


def load_dotenv(env_path: Optional[Path]) -> Dict[str, str]:
    path = Path(env_path) if env_path is not None else Path.cwd() / ".env"
    if not path.exists():
        return {}
    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        values[key.strip()] = _parse_dotenv_value(value.strip())
    return values


def _parse_dotenv_value(raw_value: str) -> str:
    if not raw_value:
        return ""
    if raw_value[0] in {'"', "'"}:
        quote = raw_value[0]
        closing_index = raw_value.find(quote, 1)
        if closing_index != -1:
            return raw_value[1:closing_index]
        return raw_value[1:]

    value_chars: list[str] = []
    for index, char in enumerate(raw_value):
        if char == "#" and (index == 0 or raw_value[index - 1].isspace()):
            break
        value_chars.append(char)
    return "".join(value_chars).strip()


def merge_env(dotenv_values: Mapping[str, str]) -> Dict[str, str]:
    merged = dict(dotenv_values)
    merged.update(os.environ)
    return merged
