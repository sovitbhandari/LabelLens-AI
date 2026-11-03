"""Version-aware keyword, vector, and hybrid retrieval."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.entities import DocumentChunk, RetrievalQuery
from app.processing.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.rrf import reciprocal_rank_fusion

logger = get_logger(__name__)

RetrievalMode = Literal["keyword", "vector", "hybrid"]


@dataclass
class RetrievedPassage:
    chunk_id: str
    passage_id: str
    set_id: str
    spl_version: int
    section_title: str | None
    text_content: str
    score: float
    rank: int
    sources: dict[str, Any]


class RetrievalService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        embedder: EmbeddingProvider | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.embedder = embedder

    def search(
        self,
        *,
        question: str,
        set_id: str,
        spl_version: int,
        mode: RetrievalMode = "hybrid",
        top_k: int | None = None,
        section_loinc: str | None = None,
        persist: bool = True,
    ) -> tuple[list[RetrievedPassage], RetrievalQuery | None]:
        top_k = top_k or self.settings.retrieval_top_k
        started = time.perf_counter()

        if mode == "keyword":
            passages = self.keyword_search(
                question, set_id=set_id, spl_version=spl_version, top_k=top_k
            )
        elif mode == "vector":
            passages = self.vector_search(
                question, set_id=set_id, spl_version=spl_version, top_k=top_k
            )
        elif mode == "hybrid":
            passages = self.hybrid_search(
                question, set_id=set_id, spl_version=spl_version, top_k=top_k
            )
        else:
            raise ValueError(f"Unsupported retrieval mode: {mode}")

        # Optional section filter after retrieval (keeps scoring intact)
        if section_loinc:
            filtered = []
            for p in passages:
                chunk = self.db.get(DocumentChunk, p.chunk_id)
                if chunk and chunk.section and chunk.section.section_loinc == section_loinc:
                    filtered.append(p)
            passages = filtered

        latency_ms = (time.perf_counter() - started) * 1000
        query_row = None
        if persist:
            query_row = RetrievalQuery(
                question=question,
                set_id=set_id,
                spl_version=spl_version,
                mode=mode,
                top_k=top_k,
                latency_ms=latency_ms,
                result_chunk_ids=[p.chunk_id for p in passages],
                scores={p.passage_id: p.score for p in passages},
            )
            self.db.add(query_row)
            self.db.commit()
            self.db.refresh(query_row)

        logger.info(
            "retrieval_completed",
            mode=mode,
            set_id=set_id,
            spl_version=spl_version,
            hits=len(passages),
            latency_ms=latency_ms,
        )
        return passages, query_row

    def keyword_search(
        self,
        question: str,
        *,
        set_id: str,
        spl_version: int,
        top_k: int,
    ) -> list[RetrievedPassage]:
        sql = text(
            """
            SELECT id, passage_id, set_id, spl_version, section_title, text_content,
                   ts_rank_cd(search_vector, plainto_tsquery('english', :q)) AS score
            FROM document_chunks
            WHERE set_id = :set_id
              AND spl_version = :spl_version
              AND search_vector @@ plainto_tsquery('english', :q)
            ORDER BY score DESC
            LIMIT :top_k
            """
        )
        rows = self.db.execute(
            sql,
            {
                "q": question,
                "set_id": set_id,
                "spl_version": spl_version,
                "top_k": top_k,
            },
        ).mappings().all()

        return [
            RetrievedPassage(
                chunk_id=row["id"],
                passage_id=row["passage_id"],
                set_id=row["set_id"],
                spl_version=row["spl_version"],
                section_title=row["section_title"],
                text_content=row["text_content"],
                score=float(row["score"]),
                rank=i,
                sources={"keyword": float(row["score"])},
            )
            for i, row in enumerate(rows, start=1)
        ]

    def vector_search(
        self,
        question: str,
        *,
        set_id: str,
        spl_version: int,
        top_k: int,
    ) -> list[RetrievedPassage]:
        embedder = self.embedder or get_embedding_provider()
        query_vec = embedder.embed([question])[0]
        # Exact cosine distance via pgvector; smaller distance = more similar
        sql = text(
            """
            SELECT c.id, c.passage_id, c.set_id, c.spl_version, c.section_title, c.text_content,
                   (e.embedding <=> CAST(:embedding AS vector)) AS distance
            FROM chunk_embeddings e
            JOIN document_chunks c ON c.id = e.chunk_id
            WHERE c.set_id = :set_id
              AND c.spl_version = :spl_version
              AND e.embedding_model = :model
              AND e.embedding_dimension = :dim
            ORDER BY e.embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
            """
        )
        vector_literal = "[" + ",".join(str(float(x)) for x in query_vec) + "]"
        rows = self.db.execute(
            sql,
            {
                "embedding": vector_literal,
                "set_id": set_id,
                "spl_version": spl_version,
                "model": embedder.model_id,
                "dim": embedder.dimension,
                "top_k": top_k,
            },
        ).mappings().all()

        passages: list[RetrievedPassage] = []
        for i, row in enumerate(rows, start=1):
            distance = float(row["distance"])
            score = 1.0 / (1.0 + distance)
            passages.append(
                RetrievedPassage(
                    chunk_id=row["id"],
                    passage_id=row["passage_id"],
                    set_id=row["set_id"],
                    spl_version=row["spl_version"],
                    section_title=row["section_title"],
                    text_content=row["text_content"],
                    score=score,
                    rank=i,
                    sources={"vector_distance": distance, "vector_score": score},
                )
            )
        return passages

    def hybrid_search(
        self,
        question: str,
        *,
        set_id: str,
        spl_version: int,
        top_k: int,
    ) -> list[RetrievedPassage]:
        # Over-fetch then fuse
        fetch_k = max(top_k * 3, top_k)
        keyword = self.keyword_search(
            question, set_id=set_id, spl_version=spl_version, top_k=fetch_k
        )
        vector = self.vector_search(
            question, set_id=set_id, spl_version=spl_version, top_k=fetch_k
        )
        fused = reciprocal_rank_fusion(
            [[p.chunk_id for p in keyword], [p.chunk_id for p in vector]],
            k=self.settings.rrf_k,
        )[:top_k]

        by_id: dict[str, RetrievedPassage] = {p.chunk_id: p for p in keyword + vector}
        # Enrich metadata from DB for IDs that might only appear in one list
        missing = [cid for cid, _ in fused if cid not in by_id]
        if missing:
            rows = self.db.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(missing))).all()
            for row in rows:
                by_id[row.id] = RetrievedPassage(
                    chunk_id=row.id,
                    passage_id=row.passage_id,
                    set_id=row.set_id,
                    spl_version=row.spl_version,
                    section_title=row.section_title,
                    text_content=row.text_content,
                    score=0.0,
                    rank=0,
                    sources={},
                )

        keyword_ranks = {p.chunk_id: p.rank for p in keyword}
        vector_ranks = {p.chunk_id: p.rank for p in vector}
        out: list[RetrievedPassage] = []
        for rank, (chunk_id, score) in enumerate(fused, start=1):
            base = by_id[chunk_id]
            out.append(
                RetrievedPassage(
                    chunk_id=base.chunk_id,
                    passage_id=base.passage_id,
                    set_id=base.set_id,
                    spl_version=base.spl_version,
                    section_title=base.section_title,
                    text_content=base.text_content,
                    score=score,
                    rank=rank,
                    sources={
                        "rrf": score,
                        "keyword_rank": keyword_ranks.get(chunk_id),
                        "vector_rank": vector_ranks.get(chunk_id),
                    },
                )
            )
        return out
