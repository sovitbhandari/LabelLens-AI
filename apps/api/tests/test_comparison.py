"""Historical diff correctness tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.ingestion.dailymed_client import SplDocument, SplHistoryEntry
from app.ingestion.service import IngestionService
from app.ingestion.spl_parser import parse_spl_xml
from app.models.entities import DocumentSection, LabelVersion
from app.processing.comparison import (
    compare_versions,
    diff_texts,
    is_formatting_only,
    normalize_for_compare,
)


def test_formatting_only_detection() -> None:
    left = "Hello   world.\nNext"
    right = "Hello world. Next"
    assert normalize_for_compare(left) == normalize_for_compare(right)
    assert is_formatting_only(left, right) is True


def test_diff_texts_detects_add_remove() -> None:
    added, removed, unified = diff_texts(
        "Line A.\nLine B.",
        "Line A.\nLine C.",
    )
    assert any("Line B" in r for r in removed)
    assert any("Line C" in a for a in added)
    assert "Line B" in unified or "-Line B" in unified or "Line B." in "\n".join(removed)


def test_compare_synthetic_versions(db, synthetic_spl_bytes: bytes) -> None:
    parsed = parse_spl_xml(synthetic_spl_bytes)
    # Manually insert two versions with a modified section
    from app.models.entities import Drug, DrugLabel

    drug = Drug(name="FakeDrug", generic_name="FakeDrug")
    db.add(drug)
    db.flush()
    label = DrugLabel(
        drug_id=drug.id,
        set_id=parsed.set_id,
        title=parsed.title,
        labeler=parsed.labeler,
        source_url="https://example.test",
    )
    db.add(label)
    db.flush()

    v1 = LabelVersion(
        label_id=label.id,
        set_id=parsed.set_id,
        spl_version=1,
        published_date=date(2024, 1, 1),
        source_url="https://example.test/1",
        content_sha256=parsed.content_sha256,
    )
    v2 = LabelVersion(
        label_id=label.id,
        set_id=parsed.set_id,
        spl_version=2,
        published_date=date(2025, 1, 1),
        source_url="https://example.test/2",
        content_sha256="b" * 64,
    )
    db.add_all([v1, v2])
    db.flush()

    for ordinal, section in enumerate(parsed.sections):
        db.add(
            DocumentSection(
                label_version_id=v1.id,
                section_id_root=section.section_id_root,
                section_loinc=section.section_loinc,
                section_title=section.section_title,
                display_name=section.display_name,
                ordinal=ordinal,
                text_content=section.text_content,
                text_hash=section.text_hash,
            )
        )
        altered = section.text_content
        if "WARNING" in (section.section_title or "").upper():
            altered = section.text_content + " Additional warning sentence for v2."
        from app.ingestion.spl_parser import sha256_text

        db.add(
            DocumentSection(
                label_version_id=v2.id,
                section_id_root=section.section_id_root,
                section_loinc=section.section_loinc,
                section_title=section.section_title,
                display_name=section.display_name,
                ordinal=ordinal,
                text_content=altered,
                text_hash=sha256_text(altered),
            )
        )
    db.commit()

    result = compare_versions(db, set_id=parsed.set_id, left_version=1, right_version=2)
    assert result.modified >= 1
    assert result.added == 0
    assert "formatting-only" in result.summary.lower() or "Deterministic" in result.summary
    assert any(d.change_type == "modified" for d in result.diffs)


def test_missing_version_errors(db, synthetic_spl_bytes: bytes) -> None:
    client = MagicMock()
    client.get_history.return_value = [
        SplHistoryEntry(spl_version=1, published_date=date(2024, 1, 1)),
    ]
    client.get_current_xml.return_value = SplDocument(
        set_id="11111111-2222-3333-4444-555555555555",
        spl_version=1,
        xml_bytes=synthetic_spl_bytes,
        source_url="https://example.test",
    )
    IngestionService(db, client=client).run(
        set_id="11111111-2222-3333-4444-555555555555", versions=[1]
    )
    with pytest.raises(LookupError, match="unavailable"):
        compare_versions(
            db,
            set_id="11111111-2222-3333-4444-555555555555",
            left_version=1,
            right_version=99,
        )
