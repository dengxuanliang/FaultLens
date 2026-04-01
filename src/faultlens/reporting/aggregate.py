from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from faultlens.models import AttributionResult, SummaryReport


class SummaryAccumulator:
    def __init__(self) -> None:
        self.total_cases = 0
        self.root_counter = Counter()
        self.signal_counter = Counter()
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
