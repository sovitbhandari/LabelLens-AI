"""Evaluation runner integration tests using synthetic fixtures."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from sqlalchemy import select

from app.evaluation.runner import ensure_builtin_datasets, run_evaluation
from app.ingestion.dailymed_client import SplDocument, SplHistoryEntry
from app.ingestion.service import IngestionService
from app.models.entities import DocumentSection, EvaluationDataset, LabelVersion
from app.processing.chunking import build_chunks_for_version, persist_chunks
from app.processing.embeddings import embed_chunks_for_version


def test_ensure_datasets_and_run_keyword_eval(db, synthetic_spl_bytes: bytes) -> None:
    client = MagicMock()
    client.get_history.return_value = [
        SplHistoryEntry(spl_version=1, published_date=date(2024, 1, 1)),
    ]
    client.get_current_xml.return_value = SplDocument(
        set_id="11111111-2222-3333-4444-555555555555",
        spl_version=1,
        xml_bytes=synthetic_spl_bytes,
        source_url="https://example.test/current.xml",
    )
    IngestionService(db, client=client).run(
        set_id="11111111-2222-3333-4444-555555555555", versions=[1]
    )
    version = db.scalar(select(LabelVersion))
    sections = list(
        db.scalars(select(DocumentSection).where(DocumentSection.label_version_id == version.id))
    )
    chunks = persist_chunks(db, version, build_chunks_for_version(version, sections))
    embed_chunks_for_version(db, chunks)

    ensure_builtin_datasets(db)
    dataset = db.scalar(
        select(EvaluationDataset).where(EvaluationDataset.name == "labellens-synthetic")
    )
    assert dataset is not None

    run = run_evaluation(
        db,
        dataset_id=dataset.id,
        retrieval_mode="keyword",
        top_k=5,
        run_generation=True,
        log_to_mlflow=True,
    )
    assert run.status == "completed"
    assert run.metrics is not None
    assert "recall_at_5" in run.metrics
    assert "version_filter_accuracy" in run.metrics
    assert run.metrics["version_filter_accuracy"] == 1.0
    assert run.mlflow_run_id is not None
