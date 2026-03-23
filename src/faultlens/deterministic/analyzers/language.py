from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


_NORMALIZED = {
    "py": "python",
    "python": "python",
    "golang": "go",
    "go": "go",
    "c++": "cpp",
    "cpp": "cpp",
    "cc": "cpp",
    "cxx": "cpp",
    "java": "java",
}


@dataclass
class LanguageInference:
    primary: Optional[str]
    candidates: List[str]
    source: str


def infer_language(
    *,
    inference_labels: Optional[Dict[str, str]],
    results_tags: Optional[Dict[str, str]],
    fence_language: Optional[str],
    completion_code: Optional[str],
) -> LanguageInference:
    from_labels = _normalize((inference_labels or {}).get("programming_language"))
    if from_labels is not None:
        return LanguageInference(primary=from_labels, candidates=[from_labels], source="inference_labels")

    from_results = _normalize((results_tags or {}).get("programming_language"))
    if from_results is not None:
        return LanguageInference(primary=from_results, candidates=[from_results], source="results_tags")

    from_fence = _normalize(fence_language)
    if from_fence is not None:
        return LanguageInference(primary=from_fence, candidates=[from_fence], source="fence")

    from_code = _heuristic_from_code(completion_code or "")
    if from_code is not None:
        return LanguageInference(primary=from_code, candidates=[from_code], source="heuristic")

    return LanguageInference(primary=None, candidates=[], source="unknown")


def _normalize(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return _NORMALIZED.get(value.strip().lower())


def _heuristic_from_code(code: str) -> Optional[str]:
    lowered = code.lower()
    if "def " in lowered and ":" in lowered:
        return "python"
    if "func " in lowered and "{" in lowered:
        return "go"
    if "public class " in lowered:
        return "java"
    if "#include" in lowered:
        return "cpp"
    return None
