from __future__ import annotations

from typing import Any, Dict


def build_attribution_messages(case: Dict[str, Any]) -> list[dict[str, str]]:
    findings = case.get("deterministic_findings", {})
    return [
        {
            "role": "system",
            "content": (
                "You are FaultLens. Use deterministic findings first, then provide a conservative root cause. "
                "Return JSON with root_cause, secondary_cause, explanation, observable_evidence, improvement_hints, llm_signals."
            ),
        },
        {
            "role": "user",
            "content": str(
                {
                    "task": case.get("task"),
                    "reference": case.get("reference"),
                    "completion": case.get("completion"),
                    "evaluation": case.get("evaluation"),
                    "deterministic_findings": findings,
                    "deterministic_signals": case.get("deterministic_signals", []),
                }
            ),
        },
    ]
