"""Idempotent DailyMed ingestion into PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.ingestion.dailymed_client import DailyMedClient, SplDocument
from app.ingestion.spl_parser import ParsedLabel, parse_spl_xml
from app.models.entities import DocumentSection, Drug, DrugLabel, IngestionRun, LabelVersion

logger = get_logger(__name__)

PROVENANCE_HASH_MISMATCH = "content_hash_mismatch"


class IngestionService:
    def __init__(self, db: Session, client: DailyMedClient | None = None):
        self.db = db
        self.client = client or DailyMedClient()
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def run(
        self,
        *,
        drug_name: str | None = None,
        set_id: str | None = None,
        versions: list[int] | None = None,
        max_versions: int = 2,
        ingest_latest_only: bool = False,
    ) -> IngestionRun:
        run = IngestionRun(
            status="running",
            drug_name=drug_name,
            set_id=set_id,
            requested_versions={"versions": versions, "max_versions": max_versions},
            details={},
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)

        try:
            resolved_set_id, title_hint = self._resolve_set_id(drug_name=drug_name, set_id=set_id)
            run.set_id = resolved_set_id
            history = self.client.get_history(resolved_set_id)
            if not history:
                raise ValueError(f"No version history for set_id={resolved_set_id}")

            selected = self._select_versions(history, versions, max_versions, ingest_latest_only)
            details: dict[str, Any] = {
                "title_hint": title_hint,
                "available_versions": [h.spl_version for h in history],
                "selected_versions": [v.spl_version for v in selected],
                "results": [],
            }

            sections_total = 0
            versions_ok = 0
            for entry in selected:
                result = self._ingest_one_version(
                    set_id=resolved_set_id,
                    spl_version=entry.spl_version,
                    published_date=entry.published_date,
                    title_hint=title_hint,
                    drug_name=drug_name,
                )
                details["results"].append(result)
                if result["status"] in {"ingested", "already_present"}:
                    versions_ok += 1
                    sections_total += int(result.get("sections", 0))

            run.status = "completed"
            run.versions_ingested = versions_ok
            run.sections_ingested = sections_total
            run.details = details
            run.finished_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(run)
            logger.info(
                "ingestion_completed",
                run_id=run.id,
                set_id=resolved_set_id,
                versions=versions_ok,
            )
            return run
        except Exception as exc:
            self.db.rollback()
            run = self.db.get(IngestionRun, run.id) or run
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = datetime.now(UTC)
            self.db.add(run)
            self.db.commit()
            self.db.refresh(run)
            logger.exception("ingestion_failed", run_id=run.id, error=str(exc))
            return run

    def _resolve_set_id(
        self, *, drug_name: str | None, set_id: str | None
    ) -> tuple[str, str | None]:
        if set_id:
            return set_id, None
        if not drug_name:
            raise ValueError("Either drug_name or set_id is required")
        hits = self.client.search_spls(drug_name, pagesize=10)
        if not hits:
            raise ValueError(f"No DailyMed SPLs found for drug_name={drug_name!r}")
        # Prefer exact-ish title match containing the drug name
        return hits[0].set_id, hits[0].title

    @staticmethod
    def _select_versions(history, versions, max_versions, ingest_latest_only):
        by_version = {h.spl_version: h for h in history}
        if versions:
            missing = [v for v in versions if v not in by_version]
            if missing:
                raise ValueError(
                    f"Requested versions unavailable in DailyMed history: {missing}. "
                    f"Available: {sorted(by_version)}"
                )
            return [by_version[v] for v in versions]
        ordered = sorted(history, key=lambda h: h.spl_version, reverse=True)
        if ingest_latest_only:
            return ordered[:1]
        return ordered[:max_versions]

    def _ingest_one_version(
        self,
        *,
        set_id: str,
        spl_version: int,
        published_date,
        title_hint: str | None,
        drug_name: str | None,
    ) -> dict[str, Any]:
        existing = self.db.scalar(
            select(LabelVersion).where(
                LabelVersion.set_id == set_id,
                LabelVersion.spl_version == spl_version,
            )
        )

        document = self._fetch_document(set_id, spl_version)
        parsed = parse_spl_xml(document.xml_bytes)

        if existing is not None:
            if existing.content_sha256 != parsed.content_sha256:
                existing.provenance_flag = PROVENANCE_HASH_MISMATCH
                existing.provenance_note = (
                    "Source content hash changed for an already-ingested immutable version. "
                    f"stored={existing.content_sha256} observed={parsed.content_sha256}"
                )
                self.db.commit()
                logger.warning(
                    "provenance_hash_mismatch",
                    set_id=set_id,
                    spl_version=spl_version,
                )
                return {
                    "status": "flagged_hash_mismatch",
                    "set_id": set_id,
                    "spl_version": spl_version,
                    "sections": len(existing.sections),
                }
            return {
                "status": "already_present",
                "set_id": set_id,
                "spl_version": spl_version,
                "sections": len(existing.sections),
                "label_version_id": existing.id,
            }

        drug, label = self._upsert_drug_and_label(
            parsed=parsed,
            source_url=document.source_url,
            drug_name_hint=drug_name,
            title_hint=title_hint,
        )
        version = LabelVersion(
            label_id=label.id,
            set_id=parsed.set_id,
            spl_version=parsed.spl_version,
            published_date=published_date,
            effective_time=parsed.effective_time,
            document_id=parsed.document_id,
            source_url=document.source_url,
            content_sha256=parsed.content_sha256,
        )
        self.db.add(version)
        self.db.flush()

        for section in parsed.sections:
            self.db.add(
                DocumentSection(
                    label_version_id=version.id,
                    section_id_root=section.section_id_root,
                    section_loinc=section.section_loinc,
                    section_title=section.section_title,
                    display_name=section.display_name,
                    ordinal=section.ordinal,
                    text_content=section.text_content,
                    text_hash=section.text_hash,
                )
            )

        self.db.commit()
        self.db.refresh(version)
        logger.info(
            "version_ingested",
            set_id=set_id,
            spl_version=parsed.spl_version,
            sections=len(parsed.sections),
            drug_id=drug.id,
        )
        return {
            "status": "ingested",
            "set_id": set_id,
            "spl_version": parsed.spl_version,
            "sections": len(parsed.sections),
            "label_version_id": version.id,
            "content_sha256": parsed.content_sha256,
        }

    def _fetch_document(self, set_id: str, spl_version: int) -> SplDocument:
        history = self.client.get_history(set_id)
        latest = max(history, key=lambda h: h.spl_version).spl_version if history else None
        if latest is not None and spl_version == latest:
            doc = self.client.get_current_xml(set_id)
            # Ensure version matches after parse; still return bytes with source URL
            return SplDocument(
                set_id=set_id,
                spl_version=spl_version,
                xml_bytes=doc.xml_bytes,
                source_url=doc.source_url,
            )
        return self.client.get_version_xml(set_id, spl_version)

    def _upsert_drug_and_label(
        self,
        *,
        parsed: ParsedLabel,
        source_url: str,
        drug_name_hint: str | None,
        title_hint: str | None,
    ) -> tuple[Drug, DrugLabel]:
        label = self.db.scalar(select(DrugLabel).where(DrugLabel.set_id == parsed.set_id))
        if label is not None:
            drug = self.db.get(Drug, label.drug_id)
            assert drug is not None
            return drug, label

        name = (
            parsed.drug_name
            or drug_name_hint
            or (title_hint.split("(")[0].strip() if title_hint else None)
            or parsed.title
        )
        drug = Drug(name=name, generic_name=parsed.generic_name)
        self.db.add(drug)
        self.db.flush()

        label = DrugLabel(
            drug_id=drug.id,
            set_id=parsed.set_id,
            title=parsed.title or title_hint or name,
            labeler=parsed.labeler,
            source_url=f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={parsed.set_id}",
        )
        self.db.add(label)
        self.db.flush()
        return drug, label
