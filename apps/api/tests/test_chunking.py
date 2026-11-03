"""Chunk provenance tests."""

from __future__ import annotations

from app.ingestion.spl_parser import parse_spl_xml
from app.models.entities import DocumentSection, LabelVersion
from app.processing.chunking import build_chunks_for_version, split_section_text


def test_split_section_respects_size() -> None:
    text = ("alpha beta gamma delta " * 80).strip()
    windows = split_section_text(text, chunk_size=200, overlap=40)
    assert len(windows) > 1
    assert all(len(piece) <= 220 for _, _, piece in windows)


def test_chunk_passage_ids_encode_version(synthetic_spl_bytes: bytes) -> None:
    parsed = parse_spl_xml(synthetic_spl_bytes)
    version = LabelVersion(
        id="ver-1",
        label_id="lab-1",
        set_id=parsed.set_id,
        spl_version=parsed.spl_version,
        source_url="https://example.test",
        content_sha256=parsed.content_sha256,
    )
    sections = [
        DocumentSection(
            id=f"sec-{s.ordinal}",
            label_version_id=version.id,
            section_id_root=s.section_id_root,
            section_loinc=s.section_loinc,
            section_title=s.section_title,
            display_name=s.display_name,
            ordinal=s.ordinal,
            text_content=s.text_content,
            text_hash=s.text_hash,
        )
        for s in parsed.sections
    ]
    drafts = build_chunks_for_version(version, sections)
    assert drafts
    for draft in drafts:
        assert f":v{parsed.spl_version}:" in draft.passage_id
        assert draft.passage_id.startswith(parsed.set_id)
        assert draft.section_id.startswith("sec-")
