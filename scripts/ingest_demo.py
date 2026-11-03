#!/usr/bin/env python3
"""Ingest Lipitor from DailyMed, chunk, embed, and run a sample retrieval."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.base import SessionLocal
from app.generation.service import RagService
from app.ingestion.service import IngestionService
from app.models.entities import DocumentSection, LabelVersion
from app.processing.chunking import build_chunks_for_version, persist_chunks
from app.processing.embeddings import embed_chunks_for_version
from app.retrieval.service import RetrievalService

LIPITOR_SET_ID = "a60cc18b-0631-4cf0-b021-9f52224ece65"


def main() -> int:
    configure_logging()
    log = get_logger("ingest_demo")
    settings = get_settings()
    log.info("settings", database=settings.database_url, embedding=settings.embedding_model)

    db = SessionLocal()
    try:
        service = IngestionService(db)
        # Ingest latest + one prior version for comparison readiness
        run = service.run(set_id=LIPITOR_SET_ID, max_versions=2)
        service.close()
        log.info(
            "ingestion_done",
            status=run.status,
            versions=run.versions_ingested,
            sections=run.sections_ingested,
            error=run.error_message,
        )
        if run.status != "completed":
            return 1

        versions = list(
            db.scalars(
                select(LabelVersion)
                .where(LabelVersion.set_id == LIPITOR_SET_ID)
                .order_by(LabelVersion.spl_version.desc())
            ).all()
        )
        for version in versions:
            sections = list(
                db.scalars(
                    select(DocumentSection).where(DocumentSection.label_version_id == version.id)
                ).all()
            )
            drafts = build_chunks_for_version(version, sections)
            chunks = persist_chunks(db, version, drafts)
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
                latency_ms=query.latency_ms if query else None,
            )

        answer = RagService(db).answer(
            question=question,
            set_id=latest.set_id,
            spl_version=latest.spl_version,
            mode="hybrid",
        )
        log.info(
            "rag_sample",
            answer_id=answer.id,
            abstained=answer.abstained,
            model=answer.model_identifier,
            citations=len(answer.citations),
            preview=answer.answer_text[:300],
        )
        print("\n=== FOUNDATION CHECKPOINT ===")
        print(f"set_id={latest.set_id} version={latest.spl_version}")
        print(f"answer_id={answer.id} citations={len(answer.citations)} abstained={answer.abstained}")
        for c in answer.citations:
            print(f"  cite {c.passage_id} valid={c.citation_valid} section={c.section_title}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
