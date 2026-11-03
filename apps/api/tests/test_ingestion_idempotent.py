"""Idempotent ingestion and version isolation integration tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.ingestion.dailymed_client import SplDocument, SplHistoryEntry
from app.ingestion.service import PROVENANCE_HASH_MISMATCH, IngestionService
from app.models.entities import DocumentSection, LabelVersion
from app.processing.chunking import build_chunks_for_version, persist_chunks


@pytest.fixture()
def mock_client(synthetic_spl_bytes: bytes):
    client = MagicMock()
    client.get_history.return_value = [
        SplHistoryEntry(spl_version=1, published_date=date(2024, 1, 1)),
    ]
    client.search_spls.return_value = []
    client.get_current_xml.return_value = SplDocument(
        set_id="11111111-2222-3333-4444-555555555555",
        spl_version=1,
        xml_bytes=synthetic_spl_bytes,
        source_url="https://example.test/current.xml",
    )
    client.get_version_xml.return_value = SplDocument(
        set_id="11111111-2222-3333-4444-555555555555",
        spl_version=1,
        xml_bytes=synthetic_spl_bytes,
        source_url="https://example.test/v1.zip",
    )
    return client


def test_idempotent_ingestion(db, mock_client, synthetic_spl_bytes: bytes) -> None:
    service = IngestionService(db, client=mock_client)
    run1 = service.run(set_id="11111111-2222-3333-4444-555555555555", versions=[1])
    assert run1.status == "completed"
    assert run1.versions_ingested == 1
    assert run1.sections_ingested >= 2

    run2 = service.run(set_id="11111111-2222-3333-4444-555555555555", versions=[1])
    assert run2.status == "completed"
    versions = db.scalars(select(LabelVersion)).all()
    assert len(versions) == 1
    assert run2.details["results"][0]["status"] == "already_present"


def test_hash_mismatch_flags_not_overwrite(db, mock_client, synthetic_spl_bytes: bytes) -> None:
    service = IngestionService(db, client=mock_client)
    service.run(set_id="11111111-2222-3333-4444-555555555555", versions=[1])
    version = db.scalar(select(LabelVersion))
    original_hash = version.content_sha256

    # Mutate source bytes
    altered = synthetic_spl_bytes.replace(b"FakeDrug", b"AlteredDrug", 1)
    mock_client.get_current_xml.return_value = SplDocument(
        set_id="11111111-2222-3333-4444-555555555555",
        spl_version=1,
        xml_bytes=altered,
        source_url="https://example.test/current.xml",
    )
    run = service.run(set_id="11111111-2222-3333-4444-555555555555", versions=[1])
    db.refresh(version)
    assert run.details["results"][0]["status"] == "flagged_hash_mismatch"
    assert version.content_sha256 == original_hash
    assert version.provenance_flag == PROVENANCE_HASH_MISMATCH


def test_chunk_version_isolation(db, mock_client) -> None:
    service = IngestionService(db, client=mock_client)
    service.run(set_id="11111111-2222-3333-4444-555555555555", versions=[1])
    version = db.scalar(select(LabelVersion))
    sections = list(
        db.scalars(select(DocumentSection).where(DocumentSection.label_version_id == version.id))
    )
    drafts = build_chunks_for_version(version, sections)
    chunks = persist_chunks(db, version, drafts)
    assert chunks
    assert all(c.spl_version == 1 for c in chunks)
    assert all(c.set_id == version.set_id for c in chunks)
