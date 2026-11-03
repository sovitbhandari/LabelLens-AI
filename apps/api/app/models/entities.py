"""SQLAlchemy 2.x models for LabelLens AI."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Drug(Base):
    __tablename__ = "drugs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    generic_name: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    labels: Mapped[list[DrugLabel]] = relationship(back_populates="drug")


class DrugLabel(Base):
    __tablename__ = "drug_labels"
    __table_args__ = (UniqueConstraint("set_id", name="uq_drug_labels_set_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    drug_id: Mapped[str] = mapped_column(ForeignKey("drugs.id", ondelete="CASCADE"), index=True)
    set_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    labeler: Mapped[str | None] = mapped_column(String(512))
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    drug: Mapped[Drug] = relationship(back_populates="labels")
    versions: Mapped[list[LabelVersion]] = relationship(back_populates="label")


class LabelVersion(Base):
    """Immutable after successful ingestion. Hash mismatches are flagged, never overwritten."""

    __tablename__ = "label_versions"
    __table_args__ = (
        UniqueConstraint("set_id", "spl_version", name="uq_label_versions_set_version"),
        Index("ix_label_versions_published_date", "published_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label_id: Mapped[str] = mapped_column(
        ForeignKey("drug_labels.id", ondelete="CASCADE"), index=True
    )
    set_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    spl_version: Mapped[int] = mapped_column(Integer, nullable=False)
    published_date: Mapped[date | None] = mapped_column(Date)
    effective_time: Mapped[str | None] = mapped_column(String(32))
    document_id: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_xml_path: Mapped[str | None] = mapped_column(String(1024))
    provenance_flag: Mapped[str | None] = mapped_column(String(64))
    provenance_note: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    label: Mapped[DrugLabel] = relationship(back_populates="versions")
    sections: Mapped[list[DocumentSection]] = relationship(back_populates="version")
    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="version")


class DocumentSection(Base):
    __tablename__ = "document_sections"
    __table_args__ = (
        UniqueConstraint(
            "label_version_id",
            "section_loinc",
            "ordinal",
            name="uq_document_sections_version_loinc_ord",
        ),
        Index("ix_document_sections_loinc", "section_loinc"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label_version_id: Mapped[str] = mapped_column(
        ForeignKey("label_versions.id", ondelete="CASCADE"), index=True
    )
    section_id_root: Mapped[str | None] = mapped_column(String(64))
    section_loinc: Mapped[str | None] = mapped_column(String(32))
    section_title: Mapped[str | None] = mapped_column(String(1024))
    display_name: Mapped[str | None] = mapped_column(String(512))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    version: Mapped[LabelVersion] = relationship(back_populates="sections")
    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="section")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "label_version_id",
            "passage_id",
            name="uq_document_chunks_version_passage",
        ),
        Index("ix_document_chunks_set_version", "set_id", "spl_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label_version_id: Mapped[str] = mapped_column(
        ForeignKey("label_versions.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[str] = mapped_column(
        ForeignKey("document_sections.id", ondelete="CASCADE"), index=True
    )
    set_id: Mapped[str] = mapped_column(String(64), nullable=False)
    spl_version: Mapped[int] = mapped_column(Integer, nullable=False)
    passage_id: Mapped[str] = mapped_column(String(128), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_title: Mapped[str | None] = mapped_column(String(1024))
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    version: Mapped[LabelVersion] = relationship(back_populates="chunks")
    section: Mapped[DocumentSection] = relationship(back_populates="chunks")
    embeddings: Mapped[list[ChunkEmbedding]] = relationship(back_populates="chunk")


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "embedding_model",
            name="uq_chunk_embeddings_chunk_model",
        ),
        Index("ix_chunk_embeddings_model_dim", "embedding_model", "embedding_dimension"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), index=True
    )
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(256), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    # Default local model is 384-d (all-MiniLM-L6-v2). Incompatible models are rejected in code.
    embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    chunk: Mapped[DocumentChunk] = relationship(back_populates="embeddings")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    drug_name: Mapped[str | None] = mapped_column(String(512))
    set_id: Mapped[str | None] = mapped_column(String(64))
    requested_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    versions_ingested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sections_ingested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RetrievalQuery(Base):
    __tablename__ = "retrieval_queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    set_id: Mapped[str | None] = mapped_column(String(64))
    spl_version: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    result_chunk_ids: Mapped[list[Any] | None] = mapped_column(JSONB)
    scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GeneratedAnswer(Base):
    __tablename__ = "generated_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    retrieval_query_id: Mapped[str | None] = mapped_column(
        ForeignKey("retrieval_queries.id", ondelete="SET NULL"), index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieval_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    referenced_versions: Mapped[list[Any] | None] = mapped_column(JSONB)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    citations: Mapped[list[Citation]] = relationship(back_populates="answer")


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    answer_id: Mapped[str] = mapped_column(
        ForeignKey("generated_answers.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), index=True
    )
    passage_id: Mapped[str] = mapped_column(String(128), nullable=False)
    set_id: Mapped[str] = mapped_column(String(64), nullable=False)
    spl_version: Mapped[int] = mapped_column(Integer, nullable=False)
    section_title: Mapped[str | None] = mapped_column(String(1024))
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    citation_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    support_note: Mapped[str | None] = mapped_column(Text)

    answer: Mapped[GeneratedAnswer] = relationship(back_populates="citations")


class EvaluationDataset(Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_eval_datasets_name_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    items: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True
    )
    pipeline_configuration_id: Mapped[str | None] = mapped_column(
        ForeignKey("pipeline_configurations.id", ondelete="SET NULL")
    )
    retrieval_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    failure_cases: Mapped[list[Any] | None] = mapped_column(JSONB)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PipelineConfiguration(Base):
    __tablename__ = "pipeline_configurations"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_pipeline_configs_name_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(256), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieval_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    rrf_k: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_revision: Mapped[str | None] = mapped_column(String(128))
    mlflow_model_version: Mapped[str | None] = mapped_column(String(64))
    alias: Mapped[str | None] = mapped_column(String(64))
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
