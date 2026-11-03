"""Parse Structured Product Labeling (HL7 v3) XML into normalized sections."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

HL7_NS = {"hl7": "urn:hl7-org:v3"}
WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class ParsedSection:
    section_id_root: str | None
    section_loinc: str | None
    display_name: str | None
    section_title: str | None
    text_content: str
    ordinal: int
    text_hash: str


@dataclass
class ParsedLabel:
    set_id: str
    spl_version: int
    document_id: str | None
    title: str
    labeler: str | None
    effective_time: str | None
    content_sha256: str
    sections: list[ParsedSection] = field(default_factory=list)
    generic_name: str | None = None
    drug_name: str | None = None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _element_text(element: etree._Element | None) -> str:
    if element is None:
        return ""
    parts: list[str] = []
    if element.text:
        parts.append(element.text)
    for child in element:
        # Skip media / rendering noise
        if _local(child.tag) in {"renderMultiMedia", "linkHtml"}:
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(_element_text(child))
        if child.tail:
            parts.append(child.tail)
    return normalize_whitespace(" ".join(parts))


def parse_spl_xml(xml_bytes: bytes) -> ParsedLabel:
    content_hash = sha256_bytes(xml_bytes)
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Invalid SPL XML: {exc}") from exc

    set_id_el = root.find("hl7:setId", namespaces=HL7_NS)
    version_el = root.find("hl7:versionNumber", namespaces=HL7_NS)
    id_el = root.find("hl7:id", namespaces=HL7_NS)
    title = _element_text(root.find("hl7:title", namespaces=HL7_NS))
    effective = root.find("hl7:effectiveTime", namespaces=HL7_NS)

    if set_id_el is None or not set_id_el.get("root"):
        raise ValueError("SPL missing setId")
    if version_el is None or version_el.get("value") is None:
        raise ValueError("SPL missing versionNumber")

    labeler = root.findtext(
        ".//hl7:author/hl7:assignedEntity/hl7:representedOrganization/hl7:name",
        namespaces=HL7_NS,
    )
    generic = root.findtext(
        ".//hl7:genericMedicine/hl7:name",
        namespaces=HL7_NS,
    )
    drug_name = root.findtext(
        ".//hl7:manufacturedProduct/hl7:manufacturedProduct/hl7:name",
        namespaces=HL7_NS,
    )

    sections = _extract_sections(root)

    return ParsedLabel(
        set_id=set_id_el.get("root"),
        spl_version=int(version_el.get("value")),
        document_id=id_el.get("root") if id_el is not None else None,
        title=title or (drug_name or "Untitled SPL"),
        labeler=normalize_whitespace(labeler) if labeler else None,
        effective_time=effective.get("value") if effective is not None else None,
        content_sha256=content_hash,
        sections=sections,
        generic_name=normalize_whitespace(generic) if generic else None,
        drug_name=normalize_whitespace(drug_name) if drug_name else None,
    )


def _extract_sections(root: etree._Element) -> list[ParsedSection]:
    """Extract leaf-ish narrative sections with LOINC codes and text."""
    results: list[ParsedSection] = []
    ordinal = 0

    for section in root.findall(".//hl7:section", namespaces=HL7_NS):
        code_el = section.find("hl7:code", namespaces=HL7_NS)
        id_el = section.find("hl7:id", namespaces=HL7_NS)
        title_el = section.find("hl7:title", namespaces=HL7_NS)
        text_el = section.find("hl7:text", namespaces=HL7_NS)

        loinc = code_el.get("code") if code_el is not None else None
        display = code_el.get("displayName") if code_el is not None else None
        title = _element_text(title_el) if title_el is not None else None
        body = _element_text(text_el) if text_el is not None else ""

        # Skip empty structural wrappers that only contain nested sections
        if not body:
            continue

        # Prefer human title; fall back to LOINC display name
        section_title = title or display or loinc or f"section-{ordinal}"
        text_content = body
        results.append(
            ParsedSection(
                section_id_root=id_el.get("root") if id_el is not None else None,
                section_loinc=loinc,
                display_name=display,
                section_title=section_title,
                text_content=text_content,
                ordinal=ordinal,
                text_hash=sha256_text(text_content),
            )
        )
        ordinal += 1

    return results


def parsed_label_to_dict(parsed: ParsedLabel) -> dict[str, Any]:
    return {
        "set_id": parsed.set_id,
        "spl_version": parsed.spl_version,
        "document_id": parsed.document_id,
        "title": parsed.title,
        "labeler": parsed.labeler,
        "effective_time": parsed.effective_time,
        "content_sha256": parsed.content_sha256,
        "generic_name": parsed.generic_name,
        "drug_name": parsed.drug_name,
        "section_count": len(parsed.sections),
        "sections": [
            {
                "ordinal": s.ordinal,
                "section_loinc": s.section_loinc,
                "section_title": s.section_title,
                "display_name": s.display_name,
                "text_hash": s.text_hash,
                "text_length": len(s.text_content),
            }
            for s in parsed.sections
        ],
    }
