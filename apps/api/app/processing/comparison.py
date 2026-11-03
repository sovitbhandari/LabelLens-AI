"""Deterministic historical label comparison engine.

LLM summaries are optional and must never be the sole change detector.
"""

from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.entities import DocumentSection, LabelVersion

logger = get_logger(__name__)

WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class SectionDiff:
    section_key: str
    left_title: str | None
    right_title: str | None
    left_loinc: str | None
    right_loinc: str | None
    change_type: str  # unchanged | added | removed | modified | formatting_only
    left_text: str
    right_text: str
    added_spans: list[str] = field(default_factory=list)
    removed_spans: list[str] = field(default_factory=list)
    unified_diff: str = ""


@dataclass
class ComparisonResult:
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
    diffs: list[SectionDiff]
    summary: str
    created_at: datetime


# In-memory store for MVP comparison results (persisted responses via API id)
_COMPARISON_STORE: dict[str, ComparisonResult] = {}


def normalize_for_compare(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip().lower()


def is_formatting_only(left: str, right: str) -> bool:
    return normalize_for_compare(left) == normalize_for_compare(right) and left != right


def _section_key(section: DocumentSection) -> str:
    if section.section_loinc:
        return f"loinc:{section.section_loinc}"
    title = normalize_for_compare(section.section_title or "")
    return f"title:{title or section.ordinal}"


def align_sections(
    left: list[DocumentSection], right: list[DocumentSection]
) -> list[tuple[DocumentSection | None, DocumentSection | None, str]]:
    left_map: dict[str, list[DocumentSection]] = {}
    right_map: dict[str, list[DocumentSection]] = {}
    for s in left:
        left_map.setdefault(_section_key(s), []).append(s)
    for s in right:
        right_map.setdefault(_section_key(s), []).append(s)

    keys = sorted(set(left_map) | set(right_map))
    pairs: list[tuple[DocumentSection | None, DocumentSection | None, str]] = []
    for key in keys:
        l_list = left_map.get(key, [])
        r_list = right_map.get(key, [])
        n = max(len(l_list), len(r_list))
        for i in range(n):
            left_item = l_list[i] if i < len(l_list) else None
            right_item = r_list[i] if i < len(r_list) else None
            pairs.append((left_item, right_item, key))
    return pairs


def diff_texts(left_text: str, right_text: str) -> tuple[list[str], list[str], str]:
    left_lines = (left_text or "").splitlines() or [left_text or ""]
    right_lines = (right_text or "").splitlines() or [right_text or ""]
    # Prefer paragraph-ish splitting when single long line
    if len(left_lines) == 1 and len(left_text) > 200:
        left_lines = [p.strip() for p in re.split(r"(?<=\.)\s+", left_text) if p.strip()]
    if len(right_lines) == 1 and len(right_text) > 200:
        right_lines = [p.strip() for p in re.split(r"(?<=\.)\s+", right_text) if p.strip()]

    matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines)
    added: list[str] = []
    removed: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "delete":
            removed.extend(left_lines[i1:i2])
        elif tag == "insert":
            added.extend(right_lines[j1:j2])
        elif tag == "replace":
            removed.extend(left_lines[i1:i2])
            added.extend(right_lines[j1:j2])

    unified = "\n".join(
        difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile="left",
            tofile="right",
            lineterm="",
        )
    )
    return added, removed, unified


def compare_versions(
    db: Session,
    *,
    set_id: str,
    left_version: int,
    right_version: int,
) -> ComparisonResult:
    left = db.scalar(
        select(LabelVersion).where(
            LabelVersion.set_id == set_id,
            LabelVersion.spl_version == left_version,
        )
    )
    right = db.scalar(
        select(LabelVersion).where(
            LabelVersion.set_id == set_id,
            LabelVersion.spl_version == right_version,
        )
    )
    if left is None or right is None:
        missing = []
        if left is None:
            missing.append(f"v{left_version}")
        if right is None:
            missing.append(f"v{right_version}")
        raise LookupError(
            f"Requested historical version unavailable for set_id={set_id}: {', '.join(missing)}"
        )

    left_sections = list(
        db.scalars(
            select(DocumentSection)
            .where(DocumentSection.label_version_id == left.id)
            .order_by(DocumentSection.ordinal)
        ).all()
    )
    right_sections = list(
        db.scalars(
            select(DocumentSection)
            .where(DocumentSection.label_version_id == right.id)
            .order_by(DocumentSection.ordinal)
        ).all()
    )

    diffs: list[SectionDiff] = []
    counts = {"unchanged": 0, "added": 0, "removed": 0, "modified": 0, "formatting_only": 0}

    for lsec, rsec, key in align_sections(left_sections, right_sections):
        if lsec is None and rsec is not None:
            change = "added"
            added, removed, unified = [rsec.text_content], [], ""
            diff = SectionDiff(
                section_key=key,
                left_title=None,
                right_title=rsec.section_title,
                left_loinc=None,
                right_loinc=rsec.section_loinc,
                change_type=change,
                left_text="",
                right_text=rsec.text_content,
                added_spans=added,
                removed_spans=removed,
                unified_diff=unified,
            )
        elif rsec is None and lsec is not None:
            change = "removed"
            diff = SectionDiff(
                section_key=key,
                left_title=lsec.section_title,
                right_title=None,
                left_loinc=lsec.section_loinc,
                right_loinc=None,
                change_type=change,
                left_text=lsec.text_content,
                right_text="",
                added_spans=[],
                removed_spans=[lsec.text_content],
                unified_diff="",
            )
        else:
            assert lsec is not None and rsec is not None
            if lsec.text_hash == rsec.text_hash:
                change = "unchanged"
                added, removed, unified = [], [], ""
            elif is_formatting_only(lsec.text_content, rsec.text_content):
                change = "formatting_only"
                added, removed, unified = diff_texts(lsec.text_content, rsec.text_content)
            else:
                change = "modified"
                added, removed, unified = diff_texts(lsec.text_content, rsec.text_content)
            diff = SectionDiff(
                section_key=key,
                left_title=lsec.section_title,
                right_title=rsec.section_title,
                left_loinc=lsec.section_loinc,
                right_loinc=rsec.section_loinc,
                change_type=change,
                left_text=lsec.text_content,
                right_text=rsec.text_content,
                added_spans=added[:20],
                removed_spans=removed[:20],
                unified_diff=unified[:5000],
            )

        counts[change] += 1
        diffs.append(diff)

    summary = _deterministic_summary(
        set_id=set_id,
        left_version=left_version,
        right_version=right_version,
        counts=counts,
        diffs=diffs,
    )
    result = ComparisonResult(
        id=str(uuid.uuid4()),
        set_id=set_id,
        left_version=left_version,
        right_version=right_version,
        sections_compared=len(diffs),
        added=counts["added"],
        removed=counts["removed"],
        modified=counts["modified"],
        formatting_only=counts["formatting_only"],
        unchanged=counts["unchanged"],
        diffs=diffs,
        summary=summary,
        created_at=datetime.now(UTC),
    )
    _COMPARISON_STORE[result.id] = result
    logger.info(
        "comparison_completed",
        comparison_id=result.id,
        set_id=set_id,
        left=left_version,
        right=right_version,
        modified=result.modified,
    )
    return result


def get_comparison(comparison_id: str) -> ComparisonResult | None:
    return _COMPARISON_STORE.get(comparison_id)


def _deterministic_summary(
    *,
    set_id: str,
    left_version: int,
    right_version: int,
    counts: dict[str, int],
    diffs: list[SectionDiff],
) -> str:
    changed = [d for d in diffs if d.change_type in {"added", "removed", "modified"}]
    lines = [
        f"Deterministic comparison for set_id={set_id} v{left_version} → v{right_version}.",
        (
            f"Sections: {counts['unchanged']} unchanged, {counts['modified']} modified, "
            f"{counts['added']} added, {counts['removed']} removed, "
            f"{counts['formatting_only']} formatting-only."
        ),
        "Formatting-only changes are not described as medical or regulatory changes.",
    ]
    for d in changed[:10]:
        title = d.right_title or d.left_title or d.section_key
        lines.append(f"- {d.change_type.upper()}: {title} ({d.section_key})")
        if d.change_type == "modified":
            if d.added_spans:
                lines.append(f"  evidence added: {d.added_spans[0][:180]}")
            if d.removed_spans:
                lines.append(f"  evidence removed: {d.removed_spans[0][:180]}")
    if len(changed) > 10:
        lines.append(f"... and {len(changed) - 10} additional changed sections.")
    return "\n".join(lines)


def comparison_to_dict(result: ComparisonResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "set_id": result.set_id,
        "left_version": result.left_version,
        "right_version": result.right_version,
        "sections_compared": result.sections_compared,
        "added": result.added,
        "removed": result.removed,
        "modified": result.modified,
        "formatting_only": result.formatting_only,
        "unchanged": result.unchanged,
        "summary": result.summary,
        "created_at": result.created_at.isoformat(),
        "diffs": [
            {
                "section_key": d.section_key,
                "left_title": d.left_title,
                "right_title": d.right_title,
                "left_loinc": d.left_loinc,
                "right_loinc": d.right_loinc,
                "change_type": d.change_type,
                "left_text": d.left_text,
                "right_text": d.right_text,
                "added_spans": d.added_spans,
                "removed_spans": d.removed_spans,
                "unified_diff": d.unified_diff,
            }
            for d in result.diffs
            if d.change_type != "unchanged"
        ],
    }
