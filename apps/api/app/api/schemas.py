"""Pydantic v2 request/response schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class DrugOut(BaseModel):
    id: str
    name: str
    generic_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LabelVersionOut(BaseModel):
    id: str
    set_id: str
    spl_version: int
    published_date: date | None
    effective_time: str | None
    source_url: str
    content_sha256: str
    provenance_flag: str | None
    ingested_at: datetime

    model_config = {"from_attributes": True}


class DrugDetailOut(DrugOut):
    labels: list[dict[str, Any]] = Field(default_factory=list)


class IngestionRequest(BaseModel):
    drug_name: str | None = None
    set_id: str | None = None
    versions: list[int] | None = None
    max_versions: int = Field(default=2, ge=1, le=20)
    ingest_latest_only: bool = False
    index_after_ingest: bool = True


class IngestionRunOut(BaseModel):
    id: str
    status: str
    drug_name: str | None
    set_id: str | None
    versions_ingested: int
    sections_ingested: int
    error_message: str | None
    details: dict[str, Any] | None
    started_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class RetrievalRequest(BaseModel):
    question: str = Field(min_length=3)
    set_id: str
    spl_version: int
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=50)


class PassageOut(BaseModel):
    chunk_id: str
    passage_id: str
    set_id: str
    spl_version: int
    section_title: str | None
    text_content: str
    score: float
    rank: int
    sources: dict[str, Any]


class RetrievalResponse(BaseModel):
    query_id: str | None
    passages: list[PassageOut]
    latency_ms: float | None = None


class RagRequest(BaseModel):
    question: str = Field(min_length=3)
    set_id: str
    spl_version: int
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=50)


class CitationOut(BaseModel):
    passage_id: str
    set_id: str
    spl_version: int
    section_title: str | None
    evidence_text: str
    citation_valid: bool

    model_config = {"from_attributes": True}


class RagAnswerOut(BaseModel):
    id: str
    question: str
    answer_text: str
    abstained: bool
    model_identifier: str
    pipeline_version: str
    prompt_template_version: str
    referenced_versions: list[Any] | None
    retrieval_config: dict[str, Any] | None
    latency_ms: float | None
    citations: list[CitationOut]

    model_config = {"from_attributes": True}


class OverviewStats(BaseModel):
    drugs: int
    label_versions: int
    sections: int
    chunks: int
    last_ingestion: IngestionRunOut | None


class CompareRequest(BaseModel):
    set_id: str
    left_version: int
    right_version: int


class CompareResponse(BaseModel):
    id: str
    set_id: str
    left_version: int
    right_version: int
    sections_compared: int
    added: int
    removed: int
    modified: int
    formatting_only: int
    unchanged: int
    summary: str
    created_at: str
    diffs: list[dict[str, Any]]


class EvaluationRunRequest(BaseModel):
    dataset_id: str | None = None
    dataset_name: str | None = None
    dataset_version: str | None = None
    retrieval_mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=50)
    run_generation: bool = True
    log_to_mlflow: bool = True


class EvaluationDatasetOut(BaseModel):
    id: str
    name: str
    version: str
    description: str | None
    is_synthetic: bool
    item_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class EvaluationRunOut(BaseModel):
    id: str
    dataset_id: str
    pipeline_configuration_id: str | None
    retrieval_mode: str
    status: str
    metrics: dict[str, Any] | None
    failure_cases: list[Any] | None
    mlflow_run_id: str | None
    started_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class ModelPromoteRequest(BaseModel):
    pipeline_id: str
    min_recall_at_5: float = 0.3
    min_citation_validity: float = 0.9


class ModelRegisterRequest(BaseModel):
    evaluation_run_id: str

