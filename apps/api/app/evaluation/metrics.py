"""Retrieval and generation evaluation metrics."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def recall_at_k(relevant: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(retrieved[:k])
    hits = sum(1 for r in relevant if r in top)
    return hits / len(relevant)


def mrr(relevant: Sequence[str], retrieved: Sequence[str]) -> float:
    relevant_set = set(relevant)
    for idx, item in enumerate(retrieved, start=1):
        if item in relevant_set:
            return 1.0 / idx
    return 0.0


def precision_at_k(relevant: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top = retrieved[:k]
    if not top:
        return 0.0
    relevant_set = set(relevant)
    hits = sum(1 for item in top if item in relevant_set)
    return hits / len(top)


def mean(values: Iterable[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0
