from __future__ import annotations

import json
from typing import Any, Dict


def build_attribution_messages(case: Dict[str, Any]) -> list[dict[str, str]]:
    findings = case.get("deterministic_findings", {})
    payload = {
        "task": case.get("task"),
        "reference": case.get("reference"),
        "completion": case.get("completion"),
        "evaluation": case.get("evaluation"),
        "deterministic_findings": findings,
        "deterministic_signals": case.get("deterministic_signals", []),
    }
    return [
        {
            "role": "system",
            "content": (
                "You are FaultLens. Use deterministic findings first, then provide a conservative root cause. "
                "Return exactly one JSON object and nothing else. "
                "If you still choose freeform text, include clearly labeled sections for Root Cause, Secondary Cause, Explanation, Evidence, and Improvement Hints. "
                "Allowed root cause categories are: task_misunderstanding, contract_or_interface_violation, solution_incorrect, "
                "implementation_bug, incomplete_or_truncated_solution, environment_or_api_mismatch, possible_evaluation_mismatch, insufficient_evidence."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        },
    ]
