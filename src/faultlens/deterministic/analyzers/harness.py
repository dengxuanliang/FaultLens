from __future__ import annotations

import ast
import re
from typing import Dict, List, Optional, Tuple

from faultlens.deterministic.signals import normalize_signals


_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_DEF_RE = re.compile(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_GO_ENTRY_RE = re.compile(r"\bfunc\s+main\s*\(")
_JAVA_ENTRY_RE = re.compile(r"\bpublic\s+static\s+void\s+main\s*\(")


def run_syntax_hook(language: Optional[str], code: Optional[str]) -> Tuple[str, Optional[str]]:
    if not code or not code.strip():
        return "no_code", None
    lang = (language or "").strip().lower()
    if lang == "python":
        try:
            ast.parse(code)
            return "parsed", None
        except SyntaxError as exc:
            excerpt = f"{exc.msg} (line {exc.lineno})"
            return "syntax_error", excerpt

    if lang in {"cpp", "java", "go"}:
        # Lightweight hook before toolchain execution: unmatched braces are a strong parse hint.
        if code.count("{") != code.count("}"):
            return "syntax_error", "brace mismatch"
        return "parsed", None

    return "not_supported", None


def analyze_harness_alignment(
    *,
    test_code: Optional[str],
    completion_code: Optional[str],
    language: Optional[str],
    accepted: Optional[bool],
    pass_metrics: Optional[Dict[str, object]],
) -> Dict[str, object]:
    signals: List[str] = []
    parse_status, parse_error_excerpt = run_syntax_hook(language, completion_code)
    if parse_status == "syntax_error":
        signals.append("syntax_error")

    signature_check_status = "unknown"
    entrypoint_check_status = "unknown"
    api_check_status = "unknown"

    if (language or "").lower() == "python":
        expected = _expected_symbol_from_test(test_code or "")
        defined = set(_DEF_RE.findall(completion_code or ""))
        if expected is None:
            signature_check_status = "unknown"
            entrypoint_check_status = "ok"
            api_check_status = "ok"
        elif expected in defined:
            signature_check_status = "ok"
            entrypoint_check_status = "ok"
            api_check_status = "ok"
        else:
            signature_check_status = "mismatch"
            entrypoint_check_status = "mismatch"
            api_check_status = "mismatch"
            signals.extend(["signature_mismatch", "entrypoint_mismatch", "api_mismatch"])
    elif (language or "").lower() == "go":
        expected = _expected_symbol_from_test(test_code or "")
        defined = set(re.findall(r"\bfunc\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", completion_code or ""))
        if expected is None:
            has_entry = bool(_GO_ENTRY_RE.search(completion_code or ""))
            entrypoint_check_status = "ok" if has_entry else "unknown"
            signature_check_status = "ok" if has_entry else "unknown"
            api_check_status = "ok" if has_entry else "unknown"
        elif expected in defined:
            entrypoint_check_status = "ok"
            signature_check_status = "ok"
            api_check_status = "ok"
        else:
            entrypoint_check_status = "mismatch"
            signature_check_status = "mismatch"
            api_check_status = "mismatch"
            signals.extend(["signature_mismatch", "entrypoint_mismatch", "api_mismatch"])
    elif (language or "").lower() == "java":
        expected = _expected_java_symbol(test_code or "")
        defined_methods = set(re.findall(r"\b(?:public\s+)?(?:static\s+)?(?:final\s+)?[A-Za-z_][A-Za-z0-9_<>\[\]]*\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", completion_code or ""))
        if expected is None:
            has_entry = bool(_JAVA_ENTRY_RE.search(completion_code or ""))
            entrypoint_check_status = "ok" if has_entry else "unknown"
            signature_check_status = "ok" if has_entry else "unknown"
            api_check_status = "ok" if has_entry else "unknown"
        elif expected in defined_methods:
            entrypoint_check_status = "ok"
            signature_check_status = "ok"
            api_check_status = "ok"
        else:
            entrypoint_check_status = "mismatch"
            signature_check_status = "mismatch"
            api_check_status = "mismatch"
            signals.extend(["signature_mismatch", "entrypoint_mismatch", "api_mismatch"])

    if _has_suspicious_eval_mismatch(accepted=accepted, pass_metrics=pass_metrics):
        signals.append("suspicious_eval_mismatch")


    normalized_signals = normalize_signals(signals)
    summary = (
        f"parse={parse_status}, signature={signature_check_status}, "
        f"entrypoint={entrypoint_check_status}, api={api_check_status}"
    )
    return {
        "parse_status": parse_status,
        "parse_error_excerpt": parse_error_excerpt,
        "signature_check_status": signature_check_status,
        "entrypoint_check_status": entrypoint_check_status,
        "api_check_status": api_check_status,
        "signals": normalized_signals,
        "summary": summary,
    }


def _expected_symbol_from_test(test_code: str) -> Optional[str]:
    excluded = {"assert", "print", "len", "range", "if", "for", "while", "switch", "return", "func", "def"}
    for name in _CALL_RE.findall(test_code):
        if name in excluded:
            continue
        if re.search(rf"\b(?:def|func)\s+{name}\s*\(", test_code):
            continue
        return name
    return None


def _expected_java_symbol(test_code: str) -> Optional[str]:
    match = re.search(r"\.([A-Za-z_][A-Za-z0-9_]*)\s*\(", test_code)
    if match:
        return match.group(1)
    return _expected_symbol_from_test(test_code)


def _has_suspicious_eval_mismatch(
    *,
    accepted: Optional[bool],
    pass_metrics: Optional[Dict[str, object]],
) -> bool:
    if accepted is not False:
        return False
    metrics = pass_metrics or {}
    for key in ("passed_at_1", "pass_at_k", "all_k_correct"):
        value = metrics.get(key)
        if isinstance(value, (int, float)) and value >= 1:
            return True
        if value is True:
            return True
    return False
