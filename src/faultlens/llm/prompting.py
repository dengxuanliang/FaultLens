from __future__ import annotations

import json
from typing import Any, Dict

PROMPT_VERSION = "attribution-v2"


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
                "You are FaultLens, a conservative failure-analysis judge for code-evaluation cases. "
                "You must return exactly one JSON object and nothing else. "
                "Do not use markdown. Do not wrap the JSON in code fences. Do not include any text before or after the JSON. "
                "Base your judgment on deterministic findings first. Do not ignore deterministic findings. "
                "Do not invent evidence that is not present in the input. "
                "Your JSON object must contain exactly these fields: "
                "root_cause, secondary_cause, failure_stage, summary, explanation, observable_evidence, evidence_refs, "
                "deterministic_alignment, confidence, needs_human_review, review_reason, improvement_hints. "
                "root_cause and secondary_cause must use only: task_misunderstanding, contract_or_interface_violation, "
                "solution_incorrect, implementation_bug, incomplete_or_truncated_solution, environment_or_api_mismatch, "
                "possible_evaluation_mismatch, insufficient_evidence. "
                "failure_stage must be one of: task_understanding, interface_contract, implementation, execution_runtime, "
                "evaluation_judgment, unknown. deterministic_alignment must be one of: consistent, partially_consistent, "
                "conflicting, insufficient_deterministic_evidence. confidence must be a number between 0 and 1. "
                "observable_evidence must contain 1 to 5 concrete observable facts. evidence_refs must contain 1 to 5 input field references. "
                "improvement_hints must contain 0 to 5 actionable next steps. review_reason must be null unless needs_human_review is true. "
                "Prefer the most specific supported root cause. If deterministic findings and your judgment conflict, set deterministic_alignment to conflicting and explain why. "
                "If the case may be an evaluator or pipeline issue, prefer possible_evaluation_mismatch and set needs_human_review to true. "
                "Return valid JSON only."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        },
    ]
