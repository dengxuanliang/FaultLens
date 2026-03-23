from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


def _metric_conflicts(accepted: Any, pass_metrics: Dict[str, Any]) -> bool:
    metric_values = []
    for key in ("passed_at_1", "pass_at_k", "all_k_correct"):
        value = pass_metrics.get(key)
        if value is None:
            continue
        metric_values.append(int(value))
    if not metric_values or accepted is None:
        return False
    if accepted is True and any(value == 0 for value in metric_values):
        return True
    if accepted is False and all(value > 0 for value in metric_values):
        return True
    return False


def apply_failure_gate(case: Dict[str, Any]) -> Dict[str, Any]:
    gated = deepcopy(case)
    warnings: List[str] = []
    signals: List[str] = list(gated.get("deterministic_signals", []))

    join_status = gated.get("join_status")
    accepted = gated.get("evaluation", {}).get("accepted")
    completion_text = (gated.get("completion", {}).get("raw_text") or "").strip()
    pass_metrics = gated.get("evaluation", {}).get("pass_metrics", {})

    if join_status != "ok":
        gated["case_status"] = "join_issue"
        gated["eligible_for_llm"] = False
    elif accepted is True:
        gated["case_status"] = "passed"
        gated["eligible_for_llm"] = False
    elif accepted is False:
        if not completion_text:
            gated["case_status"] = "data_issue"
            gated["eligible_for_llm"] = False
            signals.append("missing_code")
        else:
            gated["case_status"] = "attributable_failure"
            gated["eligible_for_llm"] = True
    else:
        gated["case_status"] = "data_issue"
        gated["eligible_for_llm"] = False
        warnings.append("missing accepted label")

    if _metric_conflicts(accepted, pass_metrics):
        warnings.append("accepted label conflicts with pass metrics")
        if "suspicious_eval_mismatch" not in signals:
            signals.append("suspicious_eval_mismatch")

    gated["deterministic_signals"] = signals
    gated["failure_gate_warnings"] = warnings
    return gated
