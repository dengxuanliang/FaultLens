from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Dict, Iterable, Optional


_ALLOWED_ROOT_CAUSES = {
    "task_misunderstanding",
    "contract_or_interface_violation",
    "solution_incorrect",
    "implementation_bug",
    "incomplete_or_truncated_solution",
    "environment_or_api_mismatch",
    "possible_evaluation_mismatch",
    "insufficient_evidence",
}

_SECTION_ALIASES = {
    "root_cause": [
        "root cause",
        "primary cause",
        "cause",
        "issue",
        "结论",
        "根因",
        "原因",
        "主要原因",
        "问题",
    ],
    "secondary_cause": ["secondary cause", "次要原因", "次因", "次要问题"],
    "explanation": ["explanation", "analysis", "summary", "reasoning", "解释", "分析", "说明", "总结"],
    "evidence": ["evidence", "observations", "proof", "证据", "依据", "现象", "观察"],
    "improvement_hints": [
        "improvement hints",
        "suggestions",
        "recommendations",
        "fix",
        "next steps",
        "建议",
        "改进建议",
        "修复建议",
        "处理建议",
    ],
}

_ROOT_CAUSE_KEYWORDS = {
    "task_misunderstanding": [
        "task misunderstanding",
        "misunderstood the task",
        "misunderstood the requirement",
        "wrong requirement",
        "题意理解错误",
        "误解题意",
        "需求理解错误",
    ],
    "contract_or_interface_violation": [
        "interface violation",
        "signature mismatch",
        "api mismatch",
        "entrypoint mismatch",
        "wrong function signature",
        "函数签名",
        "接口不匹配",
        "入口函数",
        "参数不匹配",
    ],
    "solution_incorrect": [
        "solution incorrect",
        "logic mismatch",
        "wrong logic",
        "logic error",
        "incorrect solution",
        "code is incorrect",
        "incorrect",
        "fails the test",
        "wrong answer",
        "逻辑错误",
        "解法错误",
        "结果错误",
        "算法错误",
    ],
    "implementation_bug": [
        "implementation bug",
        "compile error",
        "fails to compile",
        "syntax error",
        "runtime error",
        "missing semicolon",
        "exception",
        "bug",
        "编译错误",
        "语法错误",
        "运行时错误",
        "实现错误",
        "实现bug",
    ],
    "incomplete_or_truncated_solution": [
        "incomplete",
        "truncated",
        "unfinished",
        "missing code",
        "not completed",
        "不完整",
        "截断",
        "未完成",
        "缺少代码",
    ],
    "environment_or_api_mismatch": [
        "environment mismatch",
        "dependency issue",
        "version mismatch",
        "library issue",
        "api changed",
        "环境问题",
        "依赖问题",
        "版本不匹配",
        "库不兼容",
    ],
    "possible_evaluation_mismatch": [
        "evaluation mismatch",
        "judge issue",
        "pipeline inconsistency",
        "accepted=false despite",
        "label mismatch",
        "评测结果不一致",
        "评测不一致",
        "判题问题",
        "评测流水线",
        "标签错误",
        "accepted=false",
    ],
}


@dataclass
class ParsedAttributionResponse:
    payload: Optional[Dict[str, Any]]
    status: str
    invalid_reason: Optional[str] = None


def parse_attribution_response(content: str) -> ParsedAttributionResponse:
    text = (content or "").strip()
    if not text:
        return ParsedAttributionResponse(None, "invalid", "empty_content")

    payload = _try_parse_json(text)
    if payload is not None:
        return ParsedAttributionResponse(_normalize_payload(payload), "strict_json")

    payload = _try_parse_fenced_or_embedded_json(text)
    if payload is not None:
        return ParsedAttributionResponse(_normalize_payload(payload), "adaptive_parse", "embedded_json")

    if _looks_like_code_only(text):
        return ParsedAttributionResponse(_code_only_payload(text), "salvaged", "code_only_response")

    payload = _parse_sectioned_or_freeform_text(text)
    if payload is not None:
        status = "adaptive_parse" if payload.get("root_cause") or payload.get("observable_evidence") else "salvaged"
        reason = "sectioned_text" if status == "adaptive_parse" else "freeform_text"
        return ParsedAttributionResponse(payload, status, reason)

    return ParsedAttributionResponse(None, "invalid", "non_json_content")


def _try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _try_parse_fenced_or_embedded_json(text: str) -> Optional[Dict[str, Any]]:
    for match in re.finditer(r"```(?:json|javascript|js)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL):
        candidate = match.group(1).strip()
        payload = _try_parse_json(candidate)
        if payload is not None:
            return payload

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _looks_like_code_only(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        return True
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return False
    code_like = sum(1 for line in lines if re.search(r"[{}();]|\b(def|class|return|int|void|public|package|func)\b", line))
    return code_like >= max(2, len(lines) - 1) and not any(":" in line for line in lines[:2])


def _code_only_payload(text: str) -> Dict[str, Any]:
    return {
        "root_cause": None,
        "secondary_cause": None,
        "explanation": "LLM returned code-only content; keep deterministic root-cause classification and preserve the returned code as evidence.",
        "observable_evidence": [_trim_text(text, 800)],
        "improvement_hints": [],
        "llm_signals": ["code_only_response"],
        "evidence_refs": [{"source": "llm_code_only_response"}],
    }


def _parse_sectioned_or_freeform_text(text: str) -> Optional[Dict[str, Any]]:
    sections = _collect_sections(text)
    root_cause_raw = _first_non_empty(sections.get("root_cause", []))
    secondary_raw = _first_non_empty(sections.get("secondary_cause", []))
    explanation = _merge_lines(sections.get("explanation", []))
    evidence = _clean_bullets(sections.get("evidence", []))
    hints = _clean_bullets(sections.get("improvement_hints", []))

    if not explanation:
        explanation = _freeform_explanation(text)
    if not evidence:
        evidence = _extract_global_bullets(text)
    if not hints:
        hints = _extract_hint_lines(text)

    root_cause = _infer_root_cause(root_cause_raw or text)
    secondary_cause = _infer_root_cause(secondary_raw) if secondary_raw else None

    if not any([root_cause, explanation, evidence, hints]):
        return None

    if root_cause is None and evidence:
        root_cause = _infer_root_cause("\n".join(evidence) + "\n" + explanation)

    if root_cause is None and not evidence and not hints and not _looks_like_informative_text(explanation):
        return None

    return _normalize_payload(
        {
            "root_cause": root_cause,
            "secondary_cause": secondary_cause,
            "explanation": explanation,
            "observable_evidence": evidence,
            "improvement_hints": hints,
            "llm_signals": ["adaptive_response_parser"],
            "evidence_refs": [{"source": "llm_adaptive_parser"}],
        }
    )


def _collect_sections(text: str) -> Dict[str, list[str]]:
    sections: Dict[str, list[str]] = {key: [] for key in _SECTION_ALIASES}
    current_key = "explanation"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        matched_key, remainder = _match_section_heading(line)
        if matched_key:
            current_key = matched_key
            if remainder:
                sections[current_key].append(remainder)
            continue
        sections.setdefault(current_key, []).append(line)
    return sections


def _match_section_heading(line: str) -> tuple[Optional[str], str]:
    for key, aliases in _SECTION_ALIASES.items():
        for alias in aliases:
            pattern = rf"^{re.escape(alias)}\s*[:：]\s*(.*)$"
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                return key, match.group(1).strip()
    return None, ""


def _freeform_explanation(text: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return ""
    return _trim_text(paragraphs[0], 1200)


def _extract_global_bullets(text: str) -> list[str]:
    bullets = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if re.match(r"^[-*•]\s+", line):
            bullets.append(re.sub(r"^[-*•]\s+", "", line).strip())
    return bullets[:5]




def _looks_like_informative_text(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if sum(1 for char in cleaned if char.isalnum()) < 12:
        return False
    if re.fullmatch(r"[\W_]+", cleaned):
        return False
    return any(token in cleaned for token in [".", "。", ":", "：", "because", "因此", "所以", "wrong", "错误", "issue", "问题"]) or len(cleaned.split()) >= 4

def _extract_hint_lines(text: str) -> list[str]:
    hints = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if any(token in lower for token in ["suggest", "recommend", "use ", "replace ", "should "]) or any(token in line for token in ["建议", "改进", "修复", "检查"]):
            cleaned = re.sub(r"^[-*•]\s+", "", line).strip()
            if cleaned:
                hints.append(cleaned)
    return hints[:5]


def _infer_root_cause(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    lower = text.lower()
    for root_cause, keywords in _ROOT_CAUSE_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in lower:
                return root_cause
    eval_markers = ["accepted=false", "accepted: false", "accepted false", "evaluation says", "evaluator", "evaluation mismatch", "false negative", "grading", "评测", "判题"]
    pass_markers = ["tests passed", "test_status: passed", "pass_at_k", "correct", "通过给定测试", "测试通过", "matches the canonical solution"]
    if any(token in lower for token in eval_markers) and any(token in lower for token in pass_markers):
        return "possible_evaluation_mismatch"
    return None


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    explanation = payload.get("explanation") or ""
    evidence = _ensure_list_of_strings(payload.get("observable_evidence"))
    hints = _ensure_list_of_strings(payload.get("improvement_hints"))
    llm_signals = _ensure_list_of_strings(payload.get("llm_signals"))
    refs = payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), list) else [{"source": "llm_response"}]
    root_cause = _normalize_root_cause(payload.get("root_cause"))
    secondary_cause = _normalize_root_cause(payload.get("secondary_cause"), allow_none=True)
    if not evidence and explanation:
        evidence = [_trim_text(explanation, 300)]
    return {
        "root_cause": root_cause,
        "secondary_cause": secondary_cause,
        "explanation": explanation,
        "observable_evidence": evidence,
        "improvement_hints": hints,
        "llm_signals": llm_signals,
        "evidence_refs": refs,
    }


def _normalize_root_cause(value: Any, allow_none: bool = False) -> Optional[str]:
    if value is None or value == "":
        return None if allow_none else None
    if value in _ALLOWED_ROOT_CAUSES:
        return str(value)
    inferred = _infer_root_cause(str(value))
    if inferred is not None:
        return inferred
    return None if allow_none else None


def _ensure_list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [_trim_text(value.strip(), 500)] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        output = []
        for item in value:
            text = str(item).strip()
            if text:
                output.append(_trim_text(text, 500))
        return output
    return []


def _clean_bullets(lines: Iterable[str]) -> list[str]:
    cleaned = []
    for line in lines:
        text = re.sub(r"^[-*•]\s+", "", str(line).strip())
        if text:
            cleaned.append(_trim_text(text, 500))
    return cleaned[:5]


def _merge_lines(lines: Iterable[str]) -> str:
    parts = [str(line).strip() for line in lines if str(line).strip()]
    return _trim_text("\n".join(parts), 1500) if parts else ""


def _first_non_empty(lines: Iterable[str]) -> Optional[str]:
    for line in lines:
        text = str(line).strip()
        if text:
            return text
    return None


def _trim_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]
