"""Initial LabelLens schema with pgvector and FTS.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "drugs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("generic_name", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_drugs_name", "drugs", ["name"])

    op.create_table(
        "drug_labels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("drug_id", sa.String(36), sa.ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("set_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("labeler", sa.String(512)),
        sa.Column("source_url", sa.String(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("set_id", name="uq_drug_labels_set_id"),
    )
    op.create_index("ix_drug_labels_drug_id", "drug_labels", ["drug_id"])

    op.create_table(
        "label_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "label_id", sa.String(36), sa.ForeignKey("drug_labels.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("set_id", sa.String(64), nullable=False),
        sa.Column("spl_version", sa.Integer(), nullable=False),
        sa.Column("published_date", sa.Date()),
        sa.Column("effective_time", sa.String(32)),
        sa.Column("document_id", sa.String(64)),
        sa.Column("source_url", sa.String(1024), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("raw_xml_path", sa.String(1024)),
        sa.Column("provenance_flag", sa.String(64)),
        sa.Column("provenance_note", sa.Text()),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("set_id", "spl_version", name="uq_label_versions_set_version"),
    )
    op.create_index("ix_label_versions_label_id", "label_versions", ["label_id"])
    op.create_index("ix_label_versions_set_id", "label_versions", ["set_id"])
    op.create_index("ix_label_versions_published_date", "label_versions", ["published_date"])

    op.create_table(
        "document_sections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "label_version_id",
            sa.String(36),
            sa.ForeignKey("label_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section_id_root", sa.String(64)),
        sa.Column("section_loinc", sa.String(32)),
        sa.Column("section_title", sa.String(1024)),
        sa.Column("display_name", sa.String(512)),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "label_version_id",
            "section_loinc",
            "ordinal",
            name="uq_document_sections_version_loinc_ord",
        ),
    )
    op.create_index("ix_document_sections_label_version_id", "document_sections", ["label_version_id"])
    op.create_index("ix_document_sections_loinc", "document_sections", ["section_loinc"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "label_version_id",
            sa.String(36),
            sa.ForeignKey("label_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            sa.String(36),
            sa.ForeignKey("document_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("set_id", sa.String(64), nullable=False),
        sa.Column("spl_version", sa.Integer(), nullable=False),
        sa.Column("passage_id", sa.String(128), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.String(1024)),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_end", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("label_version_id", "passage_id", name="uq_document_chunks_version_passage"),
    )
    op.create_index("ix_document_chunks_label_version_id", "document_chunks", ["label_version_id"])
    op.create_index("ix_document_chunks_section_id", "document_chunks", ["section_id"])
    op.create_index("ix_document_chunks_set_version", "document_chunks", ["set_id", "spl_version"])
    op.execute(
        "CREATE INDEX ix_document_chunks_search_vector ON document_chunks "
        "USING GIN (search_vector)"
    )

    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "chunk_id",
            sa.String(36),
            sa.ForeignKey("document_chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding_provider", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(256), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("chunk_id", "embedding_model", name="uq_chunk_embeddings_chunk_model"),
    )
    op.create_index("ix_chunk_embeddings_chunk_id", "chunk_embeddings", ["chunk_id"])
    op.create_index(
        "ix_chunk_embeddings_model_dim",
        "chunk_embeddings",
        ["embedding_model", "embedding_dimension"],
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("drug_name", sa.String(512)),
        sa.Column("set_id", sa.String(64)),
        sa.Column("requested_versions", postgresql.JSONB()),
        sa.Column("versions_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sections_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("details", postgresql.JSONB()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "pipeline_configurations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("embedding_provider", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(256), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        sa.Column("retrieval_strategy", sa.String(32), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("rrf_k", sa.Integer(), nullable=False),
        sa.Column("llm_model", sa.String(128), nullable=False),
        sa.Column("prompt_template_version", sa.String(64), nullable=False),
        sa.Column("source_revision", sa.String(128)),
        sa.Column("mlflow_model_version", sa.String(64)),
        sa.Column("alias", sa.String(64)),
        sa.Column("config_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("name", "version", name="uq_pipeline_configs_name_version"),
    )

    op.create_table(
        "retrieval_queries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("set_id", sa.String(64)),
        sa.Column("spl_version", sa.Integer()),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("result_chunk_ids", postgresql.JSONB()),
        sa.Column("scores", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "generated_answers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "retrieval_query_id",
            sa.String(36),
            sa.ForeignKey("retrieval_queries.id", ondelete="SET NULL"),
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("abstained", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model_identifier", sa.String(128), nullable=False),
        sa.Column("pipeline_version", sa.String(64), nullable=False),
        sa.Column("prompt_template_version", sa.String(64), nullable=False),
        sa.Column("retrieval_config", postgresql.JSONB()),
        sa.Column("referenced_versions", postgresql.JSONB()),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("token_usage", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_generated_answers_retrieval_query_id", "generated_answers", ["retrieval_query_id"])

    op.create_table(
        "citations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "answer_id",
            sa.String(36),
            sa.ForeignKey("generated_answers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            sa.String(36),
            sa.ForeignKey("document_chunks.id", ondelete="SET NULL"),
        ),
        sa.Column("passage_id", sa.String(128), nullable=False),
        sa.Column("set_id", sa.String(64), nullable=False),
        sa.Column("spl_version", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.String(1024)),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("citation_valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("support_note", sa.Text()),
    )
    op.create_index("ix_citations_answer_id", "citations", ["answer_id"])
    op.create_index("ix_citations_chunk_id", "citations", ["chunk_id"])

    op.create_table(
        "evaluation_datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("items", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("name", "version", name="uq_eval_datasets_name_version"),
    )

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.String(36),
            sa.ForeignKey("evaluation_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pipeline_configuration_id",
            sa.String(36),
            sa.ForeignKey("pipeline_configurations.id", ondelete="SET NULL"),
        ),
        sa.Column("retrieval_mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metrics", postgresql.JSONB()),
        sa.Column("failure_cases", postgresql.JSONB()),
        sa.Column("mlflow_run_id", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_evaluation_runs_dataset_id", "evaluation_runs", ["dataset_id"])


def downgrade() -> None:
    for table in [
        "evaluation_runs",
        "evaluation_datasets",
        "citations",
        "generated_answers",
        "retrieval_queries",
        "pipeline_configurations",
        "ingestion_runs",
        "chunk_embeddings",
        "document_chunks",
        "document_sections",
        "label_versions",
        "drug_labels",
        "drugs",
    ]:
        op.drop_table(table)
