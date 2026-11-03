"""Citation validation against retrieved passages."""

from __future__ import annotations

from dataclasses import dataclass

from app.retrieval.service import RetrievedPassage


@dataclass
class CitationCheck:
    passage_id: str
    valid: bool
    evidence_text: str
    section_title: str | None
    set_id: str
    spl_version: int
    chunk_id: str | None
    support_note: str


def validate_citations(
    cited_passage_ids: list[str],
    retrieved: list[RetrievedPassage],
) -> list[CitationCheck]:
    by_passage = {p.passage_id: p for p in retrieved}
    checks: list[CitationCheck] = []
    for pid in cited_passage_ids:
        hit = by_passage.get(pid)
        if hit is None:
            checks.append(
                CitationCheck(
                    passage_id=pid,
                    valid=False,
                    evidence_text="",
                    section_title=None,
                    set_id="",
                    spl_version=0,
                    chunk_id=None,
                    support_note="Citation identifier not present in retrieved evidence set.",
                )
            )
        else:
            checks.append(
                CitationCheck(
                    passage_id=pid,
                    valid=True,
                    evidence_text=hit.text_content,
                    section_title=hit.section_title,
                    set_id=hit.set_id,
                    spl_version=hit.spl_version,
                    chunk_id=hit.chunk_id,
                    support_note="Citation matches a retrieved passage identifier.",
                )
            )
    return checks
