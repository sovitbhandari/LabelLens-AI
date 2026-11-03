"""Section-aware chunking with stable passage identifiers."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.entities import DocumentChunk, DocumentSection, LabelVersion

logger = get_logger(__name__)


@dataclass(frozen=True)
class ChunkDraft:
    passage_id: str
    chunk_index: int
    section_id: str
    section_title: str | None
    text_content: str
    char_start: int
    char_end: int
    token_estimate: int


def estimate_tokens(text_content: str) -> int:
    # Rough English heuristic used for budgeting only.
    return max(1, len(text_content.split()))


def split_section_text(
    text_content: str,
    *,
    chunk_size: int,
    overlap: int,
) -> list[tuple[int, int, str]]:
    """Split text into overlapping character windows, preferring paragraph boundaries."""
    if not text_content:
        return []
    if len(text_content) <= chunk_size:
        return [(0, len(text_content), text_content)]

    paragraphs = text_content.split("\n")
    # If no newlines (common after whitespace normalize), use sliding window on sentences/spaces
    if len(paragraphs) == 1:
        return _sliding_windows(text_content, chunk_size=chunk_size, overlap=overlap)

    chunks: list[tuple[int, int, str]] = []
    buffer = ""
    buffer_start = 0
    cursor = 0
    for para in paragraphs:
        candidate = f"{buffer} {para}".strip() if buffer else para
        if len(candidate) <= chunk_size:
            if not buffer:
                buffer_start = cursor
            buffer = candidate
        else:
            if buffer:
                chunks.append((buffer_start, buffer_start + len(buffer), buffer))
            # paragraph itself may exceed chunk_size
            if len(para) > chunk_size:
                for start, end, piece in _sliding_windows(
                    para, chunk_size=chunk_size, overlap=overlap
                ):
                    chunks.append((cursor + start, cursor + end, piece))
                buffer = ""
            else:
                # overlap from previous buffer tail
                if chunks and overlap > 0:
                    prev = chunks[-1][2]
                    tail = prev[-overlap:]
                    buffer = f"{tail} {para}".strip()
                    buffer_start = max(0, cursor - len(tail))
                else:
                    buffer = para
                    buffer_start = cursor
        cursor += len(para) + 1  # account for joined separator approximately

    if buffer:
        chunks.append((buffer_start, buffer_start + len(buffer), buffer))
    return chunks


def _sliding_windows(
    text_content: str, *, chunk_size: int, overlap: int
) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text_content):
        end = min(len(text_content), start + chunk_size)
        # Prefer breaking on whitespace near the end
        if end < len(text_content):
            space = text_content.rfind(" ", start, end)
            if space > start + chunk_size // 2:
                end = space
        piece = text_content[start:end].strip()
        if piece:
            out.append((start, end, piece))
        if end >= len(text_content):
            break
        start = max(end - overlap, start + 1)
    return out


def build_chunks_for_version(
    version: LabelVersion,
    sections: list[DocumentSection],
    settings: Settings | None = None,
) -> list[ChunkDraft]:
    settings = settings or get_settings()
    drafts: list[ChunkDraft] = []
    for section in sections:
        windows = split_section_text(
            section.text_content,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )
        for idx, (start, end, piece) in enumerate(windows):
            loinc = section.section_loinc or "unknown"
            passage_id = f"{version.set_id}:v{version.spl_version}:{loinc}:{section.ordinal}:{idx}"
            drafts.append(
                ChunkDraft(
                    passage_id=passage_id,
                    chunk_index=idx,
                    section_id=section.id,
                    section_title=section.section_title,
                    text_content=piece,
                    char_start=start,
                    char_end=end,
                    token_estimate=estimate_tokens(piece),
                )
            )
    return drafts


def persist_chunks(
    db: Session,
    version: LabelVersion,
    drafts: list[ChunkDraft],
) -> list[DocumentChunk]:
    """Persist chunks and refresh tsvector for keyword retrieval."""
    existing = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.label_version_id == version.id)
        .all()
    )
    if existing:
        logger.info("chunks_already_present", version_id=version.id, count=len(existing))
        return existing

    rows: list[DocumentChunk] = []
    for draft in drafts:
        row = DocumentChunk(
            label_version_id=version.id,
            section_id=draft.section_id,
            set_id=version.set_id,
            spl_version=version.spl_version,
            passage_id=draft.passage_id,
            chunk_index=draft.chunk_index,
            section_title=draft.section_title,
            text_content=draft.text_content,
            char_start=draft.char_start,
            char_end=draft.char_end,
            token_estimate=draft.token_estimate,
        )
        db.add(row)
        rows.append(row)
    db.flush()

    # Populate FTS vectors
    db.execute(
        text(
            """
            UPDATE document_chunks
            SET search_vector =
                setweight(to_tsvector('english', coalesce(section_title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(text_content, '')), 'B')
            WHERE label_version_id = :version_id
            """
        ),
        {"version_id": version.id},
    )
    db.commit()
    for row in rows:
        db.refresh(row)
    logger.info("chunks_persisted", version_id=version.id, count=len(rows))
    return rows
