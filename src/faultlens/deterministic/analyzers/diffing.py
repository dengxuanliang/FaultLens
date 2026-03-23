from __future__ import annotations

import difflib
import re
from typing import Dict, Optional


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def summarize_canonical_diff(
    canonical_code: Optional[str],
    completion_code: Optional[str],
) -> Dict[str, object]:
    if not canonical_code:
        return {
            "status": "missing_reference",
            "similarity": 0.0,
            "summary": "canonical solution missing",
            "shared_tokens": [],
            "missing_tokens": [],
        }

    if not completion_code:
        return {
            "status": "missing_completion_code",
            "similarity": 0.0,
            "summary": "completion code missing",
            "shared_tokens": [],
            "missing_tokens": sorted(set(_TOKEN_RE.findall(canonical_code)))[:10],
        }

    matcher = difflib.SequenceMatcher(a=canonical_code, b=completion_code)
    similarity = round(matcher.ratio(), 4)

    canonical_tokens = set(_TOKEN_RE.findall(canonical_code))
    completion_tokens = set(_TOKEN_RE.findall(completion_code))
    shared = sorted(canonical_tokens & completion_tokens)
    missing = sorted(canonical_tokens - completion_tokens)

    snippet = " ".join(line.strip() for line in completion_code.strip().splitlines()[:2])
    summary = (
        f"similarity={similarity:.4f}; "
        f"shared sample: {', '.join(shared[:4]) or 'none'}; "
        f"missing sample: {', '.join(missing[:4]) or 'none'}; "
        f"completion snippet: {snippet[:120]}"
    )
    return {
        "status": "ok",
        "similarity": similarity,
        "summary": summary,
        "shared_tokens": shared[:20],
        "missing_tokens": missing[:20],
    }
