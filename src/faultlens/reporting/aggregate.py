from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from faultlens.models import AttributionResult, SummaryReport


def summarize_cases(results: Iterable[AttributionResult]) -> SummaryReport:
    results = list(results)
    root_counter = Counter()
    signal_counter = Counter()
    review_queue = []
    exemplars = defaultdict(list)
    cross = defaultdict(Counter)
    slices = defaultdict(lambda: defaultdict(Counter))

    for result in results:
        if result.root_cause:
            root_counter[result.root_cause] += 1
            exemplars[result.root_cause].append(result.case_id)
        for signal in result.deterministic_signals:
            signal_counter[signal] += 1
            if result.root_cause:
                cross[signal][result.root_cause] += 1
        if result.needs_human_review:
            review_queue.append(result.case_id)
        for key, value in result.slice_fields.items():
            if value is not None and result.root_cause:
                slices[key][str(value)][result.root_cause] += 1

    return SummaryReport(
        total_cases=len(results),
        root_cause_counts=dict(root_counter),
        deterministic_signal_counts=dict(signal_counter),
        review_queue=review_queue,
        slices={outer: {inner: dict(counts) for inner, counts in inner_map.items()} for outer, inner_map in slices.items()},
        exemplars={root: case_ids[:3] for root, case_ids in exemplars.items()},
        cross_analysis={signal: dict(counter) for signal, counter in cross.items()},
    )
