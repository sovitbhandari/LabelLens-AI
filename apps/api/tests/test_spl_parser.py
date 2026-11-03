"""Tests for DailyMed SPL XML parsing."""

from __future__ import annotations

from app.ingestion.spl_parser import parse_spl_xml, sha256_bytes


def test_parse_synthetic_spl(synthetic_spl_bytes: bytes) -> None:
    parsed = parse_spl_xml(synthetic_spl_bytes)
    assert parsed.set_id == "11111111-2222-3333-4444-555555555555"
    assert parsed.spl_version == 1
    assert parsed.labeler == "TEST LAB"
    assert parsed.content_sha256 == sha256_bytes(synthetic_spl_bytes)
    assert len(parsed.sections) >= 2
    titles = {s.section_title for s in parsed.sections}
    assert any("WARNING" in (t or "").upper() for t in titles)
    assert any("INDICATION" in (t or "").upper() for t in titles)
    assert all(s.text_content for s in parsed.sections)
    assert all(s.text_hash for s in parsed.sections)


def test_parse_real_lipitor_spl(real_lipitor_spl_bytes: bytes) -> None:
    parsed = parse_spl_xml(real_lipitor_spl_bytes)
    assert parsed.set_id == "a60cc18b-0631-4cf0-b021-9f52224ece65"
    assert parsed.spl_version == 8
    assert "LIPITOR" in parsed.title.upper() or (parsed.drug_name or "").upper() == "LIPITOR"
    assert len(parsed.sections) > 5
    # Boxed warning / warnings should appear in prescription labels
    loincs = {s.section_loinc for s in parsed.sections}
    assert None not in loincs or any(s.section_loinc for s in parsed.sections)


def test_version_identity_stable_across_reparse(real_lipitor_spl_bytes: bytes) -> None:
    a = parse_spl_xml(real_lipitor_spl_bytes)
    b = parse_spl_xml(real_lipitor_spl_bytes)
    assert a.set_id == b.set_id
    assert a.spl_version == b.spl_version
    assert a.content_sha256 == b.content_sha256
    assert [s.text_hash for s in a.sections] == [s.text_hash for s in b.sections]
