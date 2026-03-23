from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional


_FENCED_BLOCK_RE = re.compile(r"```([a-zA-Z0-9_+\-]*)\n(.*?)```", re.DOTALL)


@dataclass
class ExtractionResult:
    code_blocks: List[str]
    fence_languages: List[str]
    primary_code_text: Optional[str]
    explanation_text: str
    parse_status: str


def extract_code_blocks(completion: str) -> ExtractionResult:
    fenced = _FENCED_BLOCK_RE.findall(completion)
    code_blocks = [body.strip() for _, body in fenced if body.strip()]
    fence_languages = [lang.strip().lower() for lang, _ in fenced]

    if not code_blocks:
        unfenced = _extract_unfenced_candidate(completion)
        if unfenced is not None:
            code_blocks = [unfenced]
            fence_languages = [""]

    primary = code_blocks[0] if code_blocks else None
    explanation_text = _strip_fenced_blocks(completion).strip()
    parse_status = "parsed" if primary else "no_code_found"
    return ExtractionResult(
        code_blocks=code_blocks,
        fence_languages=fence_languages,
        primary_code_text=primary,
        explanation_text=explanation_text,
        parse_status=parse_status,
    )


def _strip_fenced_blocks(text: str) -> str:
    return _FENCED_BLOCK_RE.sub("", text)


def _extract_unfenced_candidate(text: str) -> Optional[str]:
    stripped = text.strip()
    if not stripped:
        return None
    keywords = (
        "def ",
        "class ",
        "func ",
        "public class ",
        "#include",
        "package ",
        "import ",
    )
    if any(keyword in stripped for keyword in keywords):
        return stripped
    return None
