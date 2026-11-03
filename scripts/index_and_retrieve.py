#!/usr/bin/env python3
"""Chunk/embed already-ingested versions and run retrieval + RAG sample."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Avoid stale Hugging Face auth interfering with public model downloads.
os.environ.pop("HF_TOKEN", None)
os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select

from app.core.logging import configure_logging, get_logger
from app.db.base import SessionLocal
from app.generation.service import RagService
from app.models.entities import DocumentChunk, DocumentSection, LabelVersion
from app.processing.chunking import build_chunks_for_version, persist_chunks
from app.processing.embeddings import embed_chunks_for_version
from app.retrieval.service import RetrievalService

LIPITOR_SET_ID = "a60cc18b-0631-4cf0-b021-9f52224ece65"


def main() -> int:
    configure_logging()
    log = get_logger("index_and_retrieve")
    db = SessionLocal()
    try:
        versions = list(
            db.scalars(
                select(LabelVersion)
                .where(LabelVersion.set_id == LIPITOR_SET_ID)
                .order_by(LabelVersion.spl_version.desc())
            ).all()
        )
        if not versions:
            log.error("no_versions_ingested")
            return 1

        for version in versions:
            sections = list(
                db.scalars(
                    select(DocumentSection).where(DocumentSection.label_version_id == version.id)
                ).all()
            )
            drafts = build_chunks_for_version(version, sections)
            chunks = persist_chunks(db, version, drafts)
            # Re-load chunks in case they already existed
            chunks = list(
                db.scalars(
                    select(DocumentChunk).where(DocumentChunk.label_version_id == version.id)
                ).all()
            )
            n = embed_chunks_for_version(db, chunks)
            log.info(
                "indexed_version",
                spl_version=version.spl_version,
                sections=len(sections),
                chunks=len(chunks),
                embeddings_created=n,
            )

        latest = versions[0]
        question = "What are the contraindications for Lipitor?"
        retrieval = RetrievalService(db)
        for mode in ("keyword", "vector", "hybrid"):
            passages, query = retrieval.search(
                question=question,
                set_id=latest.set_id,
                spl_version=latest.spl_version,
                mode=mode,  # type: ignore[arg-type]
                top_k=5,
            )
            log.info(
                "retrieval_sample",
                mode=mode,
                hits=len(passages),
                top_passage=passages[0].passage_id if passages else None,
                top_section=passages[0].section_title if passages else None,
                latency_ms=query.latency_ms if query else None,
            )

        answer = RagService(db).answer(
            question=question,
            set_id=latest.set_id,
            spl_version=latest.spl_version,
            mode="hybrid",
        )
        print("\n=== FOUNDATION CHECKPOINT ===")
        print(f"set_id={latest.set_id} version={latest.spl_version}")
        print(f"answer_id={answer.id} citations={len(answer.citations)} abstained={answer.abstained}")
        print(f"model={answer.model_identifier}")
        print(answer.answer_text[:800])
        for c in answer.citations:
            print(f"  cite {c.passage_id} valid={c.citation_valid} section={c.section_title}")
        return 0 if answer.citations else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
