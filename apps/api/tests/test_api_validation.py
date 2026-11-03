"""API request validation tests (no database required for schema checks)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.schemas import IngestionRequest, RagRequest, RetrievalRequest


def test_retrieval_request_requires_question() -> None:
    with pytest.raises(ValidationError):
        RetrievalRequest(question="ab", set_id="x", spl_version=1)


def test_rag_request_mode_literal() -> None:
    with pytest.raises(ValidationError):
        RagRequest(question="What are warnings?", set_id="x", spl_version=1, mode="magic")


def test_ingestion_request_bounds() -> None:
    with pytest.raises(ValidationError):
        IngestionRequest(set_id="x", max_versions=0)
