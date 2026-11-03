"""RAG answer generation with schema-validated structured outputs."""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.generation.citations import validate_citations
from app.models.entities import Citation, GeneratedAnswer, RetrievalQuery
from app.retrieval.service import RetrievalService, RetrievedPassage

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are LabelLens AI, a pharmaceutical labeling research assistant.
Answer ONLY using the provided evidence passages from official DailyMed SPL documents.
Rules:
- Never invent warnings, indications, dosages, or regulatory changes.
- Cite supporting passages using their exact passage_id values.
- If evidence is insufficient, set abstained=true and explain what is missing.
- Do not give patient-specific medical advice.
- Distinguish quoted evidence from interpretation.
- Put every bullet or numbered list item on its own line (never inline multiple bullets).
- When mentioning a source URL, use a full https:// DailyMed link that opens in a browser
  (prefer https://dailymed.nlm.nih.gov/dailymed/versionInfo.cfm?setid=SETID&version=N).
Return JSON matching the required schema.
"""


class StructuredAnswer(BaseModel):
    answer_text: str
    abstained: bool = False
    citation_passage_ids: list[str] = Field(default_factory=list)
    evidence_notes: str | None = None


class RagService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.retrieval = RetrievalService(db, settings=self.settings)

    def answer(
        self,
        *,
        question: str,
        set_id: str,
        spl_version: int,
        mode: str = "hybrid",
        top_k: int | None = None,
    ) -> GeneratedAnswer:
        started = time.perf_counter()
        passages, query_row = self.retrieval.search(
            question=question,
            set_id=set_id,
            spl_version=spl_version,
            mode=mode,  # type: ignore[arg-type]
            top_k=top_k,
            persist=True,
        )

        if not passages:
            structured = StructuredAnswer(
                answer_text=(
                    "Insufficient evidence: no passages were retrieved for the requested "
                    f"document version (set_id={set_id}, version={spl_version})."
                ),
                abstained=True,
                citation_passage_ids=[],
            )
            return self._persist_answer(
                question=question,
                structured=structured,
                passages=[],
                query_row=query_row,
                model_id="none",
                started=started,
                token_usage=None,
                mode=mode,
            )

        provider = self.settings.active_llm_provider
        if provider is None:
            # Deterministic evidence-only fallback when no LLM key is configured.
            structured = self._evidence_only_answer(question, passages)
            return self._persist_answer(
                question=question,
                structured=structured,
                passages=passages,
                query_row=query_row,
                model_id="evidence-only-fallback",
                started=started,
                token_usage=None,
                mode=mode,
            )

        structured, token_usage, model_id = self._generate_with_llm(question, passages, provider)
        return self._persist_answer(
            question=question,
            structured=structured,
            passages=passages,
            query_row=query_row,
            model_id=model_id,
            started=started,
            token_usage=token_usage,
            mode=mode,
        )

    def _evidence_only_answer(
        self, question: str, passages: list[RetrievedPassage]
    ) -> StructuredAnswer:
        """Return top passages as evidence without LLM synthesis when no API key."""
        joined = "\n\n".join(
            f"[{p.passage_id}] ({p.section_title})\n{p.text_content[:500]}" for p in passages[:3]
        )
        return StructuredAnswer(
            answer_text=(
                "No LLM API key is configured. Returning retrieved evidence passages only. "
                "No clinical synthesis was generated.\n\n"
                f"Question: {question}\n\nEvidence:\n{joined}"
            ),
            abstained=True,
            citation_passage_ids=[p.passage_id for p in passages[:3]],
            evidence_notes="Evidence-only fallback; LLM generation skipped.",
        )

    def _evidence_payload(self, question: str, passages: list[RetrievedPassage]) -> dict[str, Any]:
        return {
            "question": question,
            "evidence": [
                {
                    "passage_id": p.passage_id,
                    "set_id": p.set_id,
                    "spl_version": p.spl_version,
                    "section_title": p.section_title,
                    "text": p.text_content,
                }
                for p in passages
            ],
            "instructions": (
                "Use only evidence. Cite passage_id values that support each claim. "
                "If insufficient, abstain."
            ),
        }

    def _generate_with_llm(
        self,
        question: str,
        passages: list[RetrievedPassage],
        provider: str,
    ) -> tuple[StructuredAnswer, dict[str, Any], str]:
        if provider == "gemini":
            return self._generate_with_gemini(question, passages)
        return self._generate_with_openai(question, passages)

    def _generate_with_openai(
        self, question: str, passages: list[RetrievedPassage]
    ) -> tuple[StructuredAnswer, dict[str, Any], str]:
        from openai import OpenAI

        client = OpenAI(
            api_key=self.settings.openai_api_key,
            timeout=self.settings.openai_timeout_seconds,
        )
        user_prompt = self._evidence_payload(question, passages)
        response = client.chat.completions.create(
            model=self.settings.openai_model,
            temperature=self.settings.generation_temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Respond with JSON keys: answer_text, abstained, "
                        "citation_passage_ids, evidence_notes.\n"
                        + json.dumps(user_prompt)
                    ),
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        structured = StructuredAnswer.model_validate(json.loads(content))
        usage: dict[str, Any] = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return structured, usage, self.settings.openai_model

    def _generate_with_gemini(
        self, question: str, passages: list[RetrievedPassage]
    ) -> tuple[StructuredAnswer, dict[str, Any], str]:
        import httpx

        model = self.settings.gemini_model
        user_prompt = self._evidence_payload(question, passages)
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Respond with JSON keys: answer_text, abstained, "
                                "citation_passage_ids, evidence_notes.\n"
                                + json.dumps(user_prompt)
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": self.settings.generation_temperature,
                "responseMimeType": "application/json",
            },
        }
        headers = {"x-goog-api-key": self.settings.gemini_api_key}
        with httpx.Client(timeout=self.settings.gemini_timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
            if response.is_error:
                detail = response.text[:500]
                raise RuntimeError(
                    f"Gemini generateContent failed ({response.status_code}) for "
                    f"model={model}: {detail}"
                )
            body = response.json()

        candidates = body.get("candidates") or []
        parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
        content = parts[0].get("text") if parts else "{}"
        structured = StructuredAnswer.model_validate(json.loads(content or "{}"))
        usage_meta = body.get("usageMetadata") or {}
        usage = {
            "prompt_tokens": usage_meta.get("promptTokenCount"),
            "completion_tokens": usage_meta.get("candidatesTokenCount"),
            "total_tokens": usage_meta.get("totalTokenCount"),
        }
        return structured, usage, model

    def _persist_answer(
        self,
        *,
        question: str,
        structured: StructuredAnswer,
        passages: list[RetrievedPassage],
        query_row: RetrievalQuery | None,
        model_id: str,
        started: float,
        token_usage: dict[str, Any] | None,
        mode: str,
    ) -> GeneratedAnswer:
        checks = validate_citations(structured.citation_passage_ids, passages)
        # If model cited invalid IDs, force abstention note
        invalid = [c for c in checks if not c.valid]
        answer_text = structured.answer_text
        abstained = structured.abstained
        if invalid and not abstained:
            answer_text += (
                "\n\n[System] One or more citations were invalid and removed from the "
                "verified citation set."
            )

        answer = GeneratedAnswer(
            retrieval_query_id=query_row.id if query_row else None,
            question=question,
            answer_text=answer_text,
            abstained=abstained,
            model_identifier=model_id,
            pipeline_version=self.settings.pipeline_version,
            prompt_template_version=self.settings.prompt_template_version,
            retrieval_config={
                "mode": mode,
                "top_k": self.settings.retrieval_top_k,
                "rrf_k": self.settings.rrf_k,
                "embedding_model": self.settings.embedding_model,
            },
            referenced_versions=sorted(
                {f"{p.set_id}:v{p.spl_version}" for p in passages}
            ),
            latency_ms=(time.perf_counter() - started) * 1000,
            token_usage=token_usage,
        )
        self.db.add(answer)
        self.db.flush()

        for check in checks:
            if not check.valid:
                continue
            self.db.add(
                Citation(
                    answer_id=answer.id,
                    chunk_id=check.chunk_id,
                    passage_id=check.passage_id,
                    set_id=check.set_id,
                    spl_version=check.spl_version,
                    section_title=check.section_title,
                    evidence_text=check.evidence_text,
                    citation_valid=True,
                    support_note=check.support_note,
                )
            )
        self.db.commit()
        self.db.refresh(answer)
        logger.info(
            "answer_generated",
            answer_id=answer.id,
            abstained=answer.abstained,
            citations=len([c for c in checks if c.valid]),
        )
        return answer
