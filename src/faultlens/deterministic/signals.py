from __future__ import annotations

from typing import Iterable, List


CONTROLLED_SIGNALS = {
    "missing_code",
    "code_extraction_failed",
    "syntax_error",
    "compile_error",
    "runtime_error",
    "test_failure",
    "timeout",
    "signature_mismatch",
    "entrypoint_mismatch",
    "api_mismatch",
    "logic_mismatch",
    "metadata_conflict",
    "suspicious_eval_mismatch",
}


def normalize_signals(signals: Iterable[str]) -> List[str]:
    seen = set()
    normalized: List[str] = []
    for raw in signals:
        signal = raw.strip()
        if signal in CONTROLLED_SIGNALS and signal not in seen:
            seen.add(signal)
            normalized.append(signal)
    return normalized
