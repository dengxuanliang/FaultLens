from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class InputRoleResolution:
    inference_path: Path
    results_path: Path
    warnings: List[str] = field(default_factory=list)


@dataclass
class Findings:
    signals: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case_id: str
    case_status: str
    accepted: Optional[bool]
    root_cause: Optional[str] = None
    deterministic_findings: Dict[str, Any] = field(default_factory=dict)
