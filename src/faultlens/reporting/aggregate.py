from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from faultlens.models import AttributionResult, SummaryReport


class SummaryAccumulator:
    def __init__(self) -> None:
        self.total_cases = 0
        self.root_counter = Counter()
        self.signal_counter = Counter()
        self.hierarchy_counters = {"l1": Counter(), "l2": Counter(), "l3": Counter()}
        self.hierarchy_subtype_counters = {
            "l1": defaultdict(Counter),
            "l2": defaultdict(Counter),
            "l3": defaultdict(Counter),
        }
        self.hierarchy_root_cause_cross = {
            "l1": defaultdict(Counter),
            "l2": defaultdict(Counter),
            "l3": defaultdict(Counter),
        }
        self.review_queue: list[str] = []
        self.exemplars = defaultdict(list)
        self.cross = defaultdict(Counter)
        self.slices = defaultdict(lambda: defaultdict(Counter))

    def add(self, result: AttributionResult) -> None:
        self.total_cases += 1
        if result.root_cause:
            self.root_counter[result.root_cause] += 1
            if len(self.exemplars[result.root_cause]) < 3:
                self.exemplars[result.root_cause].append(result.case_id)
        for signal in result.deterministic_signals:
            self.signal_counter[signal] += 1
            if result.root_cause:
                self.cross[signal][result.root_cause] += 1
        if result.case_status == "attributable_failure":
            hierarchy = result.hierarchical_cause or {}
            for level in ("l1", "l2", "l3"):
                level_data = hierarchy.get(level) or {}
                code = level_data.get("code")
                if code:
                    self.hierarchy_counters[level][code] += 1
                    subtype = level_data.get("subtype") or "unspecified"
                    self.hierarchy_subtype_counters[level][code][subtype] += 1
                    if result.root_cause:
                        self.hierarchy_root_cause_cross[level][code][result.root_cause] += 1
        if result.needs_human_review:
            self.review_queue.append(result.case_id)
        for key, value in result.slice_fields.items():
            if value is not None and result.root_cause:
                self.slices[key][str(value)][result.root_cause] += 1

    def to_summary(self) -> SummaryReport:
        return SummaryReport(
            total_cases=self.total_cases,
            root_cause_counts=dict(self.root_counter),
            deterministic_signal_counts=dict(self.signal_counter),
            hierarchy_counts={level: dict(counter) for level, counter in self.hierarchy_counters.items()},
            hierarchy_subtype_counts={
                level: {code: dict(counter) for code, counter in grouped.items()}
                for level, grouped in self.hierarchy_subtype_counters.items()
            },
            hierarchy_root_cause_cross={
                level: {code: dict(counter) for code, counter in grouped.items()}
                for level, grouped in self.hierarchy_root_cause_cross.items()
            },
            review_queue=list(self.review_queue),
            slices={outer: {inner: dict(counts) for inner, counts in inner_map.items()} for outer, inner_map in self.slices.items()},
            exemplars={root: case_ids[:] for root, case_ids in self.exemplars.items()},
            cross_analysis={signal: dict(counter) for signal, counter in self.cross.items()},
        )



def summarize_cases(results: Iterable[AttributionResult]) -> SummaryReport:
    accumulator = SummaryAccumulator()
    for result in results:
        accumulator.add(result)
    return accumulator.to_summary()
