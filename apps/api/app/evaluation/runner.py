"""Reproducible evaluation runner for retrieval and generation."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.evaluation.metrics import mean, mrr, precision_at_k, recall_at_k
from app.generation.service import RagService
from app.mlops.tracking import log_evaluation_run
from app.models.entities import EvaluationDataset, EvaluationRun, PipelineConfiguration
from app.retrieval.service import RetrievalService

logger = get_logger(__name__)

RetrievalMode = Literal["keyword", "vector", "hybrid"]

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATASETS = [
    REPO_ROOT / "datasets" / "evaluation" / "synthetic_v1.json",
    REPO_ROOT / "datasets" / "evaluation" / "lipitor_author_curated_v1.json",
]


def load_dataset_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_builtin_datasets(db: Session) -> list[EvaluationDataset]:
    created: list[EvaluationDataset] = []
    for path in DEFAULT_DATASETS:
        if not path.exists():
            continue
        payload = load_dataset_file(path)
        existing = db.scalar(
            select(EvaluationDataset).where(
                EvaluationDataset.name == payload["name"],
                EvaluationDataset.version == payload["version"],
            )
        )
        if existing:
            created.append(existing)
            continue
        row = EvaluationDataset(
            name=payload["name"],
            version=payload["version"],
            description=payload.get("description"),
            is_synthetic=bool(payload.get("is_synthetic", False)),
            items=payload.get("items", []),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        created.append(row)
        logger.info("eval_dataset_loaded", name=row.name, version=row.version, path=str(path))
    return created


def _passage_matches_expectation(text: str, expected_substrings: list[str]) -> bool:
    lowered = text.lower()
    return any(s.lower() in lowered for s in expected_substrings)


def expire_stale_evaluation_runs(db: Session, *, older_than_minutes: int = 45) -> int:
    """Mark abandoned 'running' evaluations as failed so the UI is not stuck."""
    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    stale = list(
        db.scalars(
            select(EvaluationRun).where(
                EvaluationRun.status == "running",
                EvaluationRun.started_at < cutoff,
            )
        ).all()
    )
    for run in stale:
        run.status = "failed"
        run.failure_cases = [
            {
                "error": (
                    f"Evaluation timed out after {older_than_minutes} minutes "
                    "without completing."
                )
            }
        ]
        run.finished_at = datetime.now(UTC)
    if stale:
        db.commit()
    return len(stale)


def create_evaluation_run(
    db: Session,
    *,
    dataset_id: str,
    retrieval_mode: RetrievalMode = "hybrid",
) -> EvaluationRun:
    expire_stale_evaluation_runs(db)
    dataset = db.get(EvaluationDataset, dataset_id)
    if not dataset:
        raise LookupError(f"Evaluation dataset not found: {dataset_id}")
    run = EvaluationRun(
        dataset_id=dataset.id,
        retrieval_mode=retrieval_mode,
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_evaluation(
    db: Session,
    *,
    dataset_id: str,
    retrieval_mode: RetrievalMode = "hybrid",
    top_k: int = 5,
    run_generation: bool = True,
    log_to_mlflow: bool = True,
    settings: Settings | None = None,
    existing_run_id: str | None = None,
) -> EvaluationRun:
    settings = settings or get_settings()
    dataset = db.get(EvaluationDataset, dataset_id)
    if not dataset:
        raise LookupError(f"Evaluation dataset not found: {dataset_id}")

    if existing_run_id:
        run = db.get(EvaluationRun, existing_run_id)
        if not run:
            raise LookupError(f"Evaluation run not found: {existing_run_id}")
        run.status = "running"
        run.failure_cases = None
        run.metrics = None
        run.finished_at = None
        db.commit()
        db.refresh(run)
    else:
        run = create_evaluation_run(
            db, dataset_id=dataset.id, retrieval_mode=retrieval_mode
        )

    retrieval = RetrievalService(db, settings=settings)
    rag = RagService(db, settings=settings) if run_generation else None

    recalls: list[float] = []
    mrrs: list[float] = []
    precisions: list[float] = []
    version_ok: list[float] = []
    citation_validity: list[float] = []
    abstention_correct: list[float] = []
    unsupported: list[float] = []
    latencies: list[float] = []
    retrieval_latencies: list[float] = []
    generation_latencies: list[float] = []
    failure_cases: list[dict[str, Any]] = []
    item_results: list[dict[str, Any]] = []

    try:
        for item in dataset.items:
            question = item["question"]
            set_id = item["set_id"]
            spl_version = int(item["spl_version"])
            expected_substrings = item.get("expected_passage_substrings") or []
            answerable = bool(item.get("answerable", True))
            expected_loincs = set(item.get("expected_section_loincs") or [])

            started = time.perf_counter()
            passages, query = retrieval.search(
                question=question,
                set_id=set_id,
                spl_version=spl_version,
                mode=retrieval_mode,
                top_k=top_k,
                persist=True,
            )
            retrieval_ms = (query.latency_ms if query else (time.perf_counter() - started) * 1000)
            retrieval_latencies.append(float(retrieval_ms or 0.0))

            # Relevant IDs approximated by substring match on retrieved passages.
            relevant_ids = []
            for p in passages:
                if expected_substrings and _passage_matches_expectation(
                    p.text_content, expected_substrings
                ):
                    relevant_ids.append(p.passage_id)
            # Relevance judged against retrieved set + expected substrings.
            retrieved_ids = [p.passage_id for p in passages]
            if answerable and expected_substrings:
                # Synthetic relevance labels = matching retrieved passages; if none match,
                # invent a sentinel relevant id so recall/MRR are zero rather than undefined.
                relevant_for_metrics = relevant_ids or ["__missing_relevant__"]
            elif not answerable:
                relevant_for_metrics = []
            else:
                relevant_for_metrics = relevant_ids

            if answerable:
                recalls.append(recall_at_k(relevant_for_metrics, retrieved_ids, top_k))
                mrrs.append(mrr(relevant_for_metrics, retrieved_ids))
                precisions.append(precision_at_k(relevant_for_metrics, retrieved_ids, top_k))
            else:
                # For unanswerable: precision of empty relevance is 0 if anything retrieved
                # Version filter accuracy still applies.
                recalls.append(1.0 if not retrieved_ids else 0.0)
                mrrs.append(1.0 if not retrieved_ids else 0.0)
                precisions.append(1.0 if not retrieved_ids else 0.0)

            version_hits = all(
                p.spl_version == spl_version and p.set_id == set_id for p in passages
            )
            version_ok.append(1.0 if (not passages or version_hits) else 0.0)

            gen_ms = 0.0
            citation_valid_ratio = 1.0
            abstained = False
            if rag is not None:
                gen_started = time.perf_counter()
                answer = rag.answer(
                    question=question,
                    set_id=set_id,
                    spl_version=spl_version,
                    mode=retrieval_mode,
                    top_k=top_k,
                )
                gen_ms = (time.perf_counter() - gen_started) * 1000
                generation_latencies.append(gen_ms)
                abstained = answer.abstained
                cites = list(answer.citations)
                if cites:
                    citation_valid_ratio = sum(1 for c in cites if c.citation_valid) / len(cites)
                elif answerable and not abstained:
                    citation_valid_ratio = 0.0
                    unsupported.append(1.0)
                else:
                    unsupported.append(0.0)
                citation_validity.append(citation_valid_ratio)
                abstention_correct.append(1.0 if abstained == (not answerable) else 0.0)
            else:
                unsupported.append(0.0)

            total_ms = (time.perf_counter() - started) * 1000
            latencies.append(total_ms)

            item_result = {
                "id": item.get("id"),
                "question": question,
                "answerable": answerable,
                "retrieved": len(passages),
                "relevant_matches": len(relevant_ids),
                "recall_proxy": recalls[-1],
                "mrr_proxy": mrrs[-1],
                "version_ok": version_ok[-1],
                "abstained": abstained,
                "citation_validity": citation_valid_ratio,
                "latency_ms": total_ms,
                "top_sections": [p.section_title for p in passages[:3]],
                "expected_loincs": list(expected_loincs),
            }
            item_results.append(item_result)

            failed = False
            reason = []
            if answerable and recalls[-1] < 1.0:
                failed = True
                reason.append("recall_incomplete")
            if version_ok[-1] < 1.0:
                failed = True
                reason.append("version_leak")
            if rag is not None and abstention_correct and abstention_correct[-1] < 1.0:
                failed = True
                reason.append("abstention_mismatch")
            if failed:
                failure_cases.append({**item_result, "reasons": reason})

        def pct(values: list[float], q: float) -> float:
            if not values:
                return 0.0
            ordered = sorted(values)
            idx = min(len(ordered) - 1, max(0, int(round((q / 100) * (len(ordered) - 1)))))
            return float(ordered[idx])

        metrics = {
            "recall_at_5": mean(recalls),
            "mrr": mean(mrrs),
            "precision_at_5": mean(precisions),
            "version_filter_accuracy": mean(version_ok),
            "citation_validity": mean(citation_validity) if citation_validity else 1.0,
            "abstention_correctness": mean(abstention_correct) if abstention_correct else 1.0,
            "unsupported_claim_rate": mean(unsupported) if unsupported else 0.0,
            "latency_p50_ms": pct(latencies, 50),
            "latency_p95_ms": pct(latencies, 95),
            "retrieval_latency_p50_ms": pct(retrieval_latencies, 50),
            "generation_latency_p50_ms": (
                pct(generation_latencies, 50) if generation_latencies else 0.0
            ),
            "n_items": float(len(dataset.items)),
        }

        provider = settings.active_llm_provider
        if provider == "gemini":
            llm_model = settings.gemini_model
        elif provider == "openai":
            llm_model = settings.openai_model
        else:
            llm_model = "evidence-only-fallback"
        # Unique per run so re-running the same mode/dataset never hits
        # uq_pipeline_configs_name_version.
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        unique = uuid.uuid4().hex[:8]
        pipeline = PipelineConfiguration(
            name="labellens-rag",
            version=(
                f"{settings.pipeline_version}-{retrieval_mode}-{dataset.version}-"
                f"{stamp}-{unique}"
            ),
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
            embedding_dimension=settings.embedding_dimension,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            retrieval_strategy=retrieval_mode,
            top_k=top_k,
            rrf_k=settings.rrf_k,
            llm_model=llm_model,
            prompt_template_version=settings.prompt_template_version,
            source_revision=None,
            alias="candidate",
            config_json={
                "dataset": f"{dataset.name}:{dataset.version}",
                "metrics": metrics,
            },
        )
        db.add(pipeline)
        db.flush()
        run.pipeline_configuration_id = pipeline.id

        mlflow_run_id = None
        if log_to_mlflow:
            try:
                mlflow_run_id = log_evaluation_run(
                    params={
                        "embedding_model": settings.embedding_model,
                        "embedding_dimension": settings.embedding_dimension,
                        "chunk_size": settings.chunk_size,
                        "chunk_overlap": settings.chunk_overlap,
                        "retrieval_strategy": retrieval_mode,
                        "top_k": top_k,
                        "rrf_k": settings.rrf_k,
                        "llm_model": pipeline.llm_model,
                        "prompt_template_version": settings.prompt_template_version,
                        "dataset_version": f"{dataset.name}:{dataset.version}",
                        "pipeline_version": settings.pipeline_version,
                    },
                    metrics=metrics,
                    tags={
                        "dataset_synthetic": str(dataset.is_synthetic).lower(),
                        "retrieval_mode": retrieval_mode,
                    },
                )
            except Exception as exc:
                logger.warning("mlflow_logging_failed", error=str(exc))
                failure_cases.append({"mlflow_error": str(exc)})

        run.status = "completed"
        run.metrics = {**metrics, "item_results": item_results}
        run.failure_cases = failure_cases
        run.mlflow_run_id = mlflow_run_id
        run.finished_at = datetime.now(UTC)
        db.commit()
        db.refresh(run)
        logger.info("evaluation_completed", run_id=run.id, metrics=metrics)
        return run
    except Exception as exc:
        db.rollback()
        run = db.get(EvaluationRun, run.id) or run
        run.status = "failed"
        run.failure_cases = [{"error": str(exc)}]
        run.finished_at = datetime.now(UTC)
        db.add(run)
        db.commit()
        db.refresh(run)
        logger.exception("evaluation_failed", run_id=run.id, error=str(exc))
        return run
