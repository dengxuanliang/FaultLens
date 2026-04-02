from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class InputRoleResolution:
    inference_path: Path
    results_path: Path
    warnings: List[str] = field(default_factory=list)
    detected_roles: Dict[str, str] = field(default_factory=dict)


@dataclass
class TaskInfo:
    content_text: str
    canonical_code_text: Optional[str] = None
    test_code_text: Optional[str] = None


@dataclass
class EvaluationInfo:
    accepted: Optional[bool]
    pass_metrics: Dict[str, Any] = field(default_factory=dict)
    results_tags: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseRecord:
    case_id: str
    join_status: str
    case_status: str
    task: TaskInfo
    evaluation: EvaluationInfo
    completion_raw_text: str
    raw_inference_record: Dict[str, Any] = field(default_factory=dict)
    raw_results_record: Dict[str, Any] = field(default_factory=dict)
    source: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    language: Dict[str, Any] = field(default_factory=dict)
    completion: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    eligible_for_llm: bool = False


@dataclass
class DeterministicFindings:
    signals: List[str] = field(default_factory=list)
    findings: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    root_cause_hint: Optional[str] = None


@dataclass
class AttributionResult:
    case_id: str
    case_status: str
    accepted: Optional[bool]
    root_cause: Optional[str]
    deterministic_signals: List[str] = field(default_factory=list)
    llm_signals: List[str] = field(default_factory=list)
    observable_evidence: List[str] = field(default_factory=list)
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    deterministic_findings: Dict[str, Any] = field(default_factory=dict)
    llm_judgment: Optional[Dict[str, Any]] = None
    final_decision_source: str = "deterministic_only"
    confidence: Optional[float] = None
    needs_human_review: bool = False
    review_reason: Optional[str] = None
    improvement_hints: List[str] = field(default_factory=list)
    explanation: str = ""
    secondary_cause: Optional[str] = None
    slice_fields: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    llm_parse_mode: Optional[str] = None
    llm_parse_reason: Optional[str] = None
    llm_raw_response_excerpt: Optional[str] = None
    llm_raw_response_path: Optional[str] = None
    llm_raw_response_sha256: Optional[str] = None
    hierarchical_cause: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SummaryReport:
    total_cases: int
    root_cause_counts: Dict[str, int]
    deterministic_signal_counts: Dict[str, int]
    hierarchy_counts: Dict[str, Dict[str, int]] = field(default_factory=dict)
    hierarchy_subtype_counts: Dict[str, Dict[str, Dict[str, int]]] = field(default_factory=dict)
    hierarchy_root_cause_cross: Dict[str, Dict[str, Dict[str, int]]] = field(default_factory=dict)
    review_queue: List[str] = field(default_factory=list)
    slices: Dict[str, Dict[str, Dict[str, int]]] = field(default_factory=dict)
    exemplars: Dict[str, List[str]] = field(default_factory=dict)
    cross_analysis: Dict[str, Dict[str, int]] = field(default_factory=dict)
