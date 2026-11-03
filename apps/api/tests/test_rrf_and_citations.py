"""Unit tests for RRF and citation validation."""

from __future__ import annotations

from app.generation.citations import validate_citations
from app.retrieval.rrf import reciprocal_rank_fusion
from app.retrieval.service import RetrievedPassage


def test_reciprocal_rank_fusion_prefers_consensus() -> None:
    fused = reciprocal_rank_fusion(
        [
            ["a", "b", "c"],
            ["b", "a", "d"],
        ],
        k=60,
    )
    ranked_ids = [doc_id for doc_id, _ in fused]
    assert ranked_ids[0] in {"a", "b"}
    assert set(ranked_ids) == {"a", "b", "c", "d"}
    scores = dict(fused)
    assert scores["a"] > scores["c"]
    assert scores["b"] > scores["d"]


def test_citation_validation_accepts_retrieved_ids() -> None:
    passages = [
        RetrievedPassage(
            chunk_id="c1",
            passage_id="p1",
            set_id="s",
            spl_version=1,
            section_title="WARNINGS",
            text_content="Do not use if allergic.",
            score=1.0,
            rank=1,
            sources={},
        )
    ]
    checks = validate_citations(["p1", "missing"], passages)
    assert checks[0].valid is True
    assert checks[0].evidence_text.startswith("Do not use")
    assert checks[1].valid is False
