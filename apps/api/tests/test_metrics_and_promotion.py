from app.evaluation.metrics import mrr, precision_at_k, recall_at_k
from app.mlops.tracking import promote_candidate


def test_retrieval_metrics() -> None:
    relevant = ["a", "b"]
    retrieved = ["x", "a", "b", "y"]
    assert recall_at_k(relevant, retrieved, 5) == 1.0
    assert recall_at_k(relevant, retrieved, 1) == 0.0
    assert mrr(relevant, retrieved) == 0.5
    assert precision_at_k(relevant, retrieved, 2) == 0.5


def test_promotion_requires_thresholds() -> None:
    rejected = promote_candidate(
        candidate_version="2",
        metrics={"recall_at_5": 0.1, "citation_validity": 1.0, "mrr": 0.5},
        champion_metrics=None,
        apply_aliases=False,
    )
    assert rejected["promoted"] is False

    rejected2 = promote_candidate(
        candidate_version="3",
        metrics={"recall_at_5": 0.9, "citation_validity": 1.0, "mrr": 0.4},
        champion_metrics={"recall_at_5": 0.95, "mrr": 0.5},
        apply_aliases=False,
    )
    assert rejected2["promoted"] is False
    assert "regress" in rejected2["reason"].lower()

    accepted = promote_candidate(
        candidate_version="4",
        metrics={"recall_at_5": 0.96, "citation_validity": 1.0, "mrr": 0.55},
        champion_metrics={"recall_at_5": 0.95, "mrr": 0.5},
        apply_aliases=False,
    )
    assert accepted["promoted"] is True
