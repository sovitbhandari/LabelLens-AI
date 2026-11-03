"""FastAPI route handlers."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import (
    CompareRequest,
    CompareResponse,
    DrugDetailOut,
    DrugOut,
    EvaluationDatasetOut,
    EvaluationRunOut,
    EvaluationRunRequest,
    HealthResponse,
    IngestionRequest,
    IngestionRunOut,
    LabelVersionOut,
    ModelPromoteRequest,
    ModelRegisterRequest,
    OverviewStats,
    PassageOut,
    RagAnswerOut,
    RagRequest,
    RetrievalRequest,
    RetrievalResponse,
)
from app.core.logging import get_logger
from app.core.security import require_admin
from app.db.base import SessionLocal, check_db_ready, get_db
from app.evaluation.runner import (
    create_evaluation_run,
    ensure_builtin_datasets,
    expire_stale_evaluation_runs,
    run_evaluation,
)
from app.generation.service import RagService
from app.ingestion.service import IngestionService
from app.mlops.registry import (
    get_pipeline,
    list_registered_pipelines,
    promote_pipeline,
    register_from_evaluation,
    rollback_pipeline,
)
from app.models.entities import (
    DocumentChunk,
    DocumentSection,
    Drug,
    DrugLabel,
    EvaluationDataset,
    EvaluationRun,
    IngestionRun,
    LabelVersion,
)
from app.processing.chunking import build_chunks_for_version, persist_chunks
from app.processing.comparison import (
    compare_versions,
    comparison_to_dict,
    get_comparison,
)
from app.processing.embeddings import embed_chunks_for_version
from app.retrieval.service import RetrievalService

logger = get_logger(__name__)

router = APIRouter()
health_router = APIRouter(tags=["health"])


def _execute_evaluation_job(
    *,
    run_id: str,
    dataset_id: str,
    retrieval_mode: str,
    top_k: int,
    run_generation: bool,
    log_to_mlflow: bool,
) -> None:
    db = SessionLocal()
    try:
        run_evaluation(
            db,
            dataset_id=dataset_id,
            retrieval_mode=retrieval_mode,  # type: ignore[arg-type]
            top_k=top_k,
            run_generation=run_generation,
            log_to_mlflow=log_to_mlflow,
            existing_run_id=run_id,
        )
    except Exception:
        logger.exception("background_evaluation_failed", run_id=run_id)
    finally:
        db.close()


@health_router.get("/health/live", response_model=HealthResponse)
def live() -> HealthResponse:
    return HealthResponse(status="ok")


@health_router.get("/health/ready", response_model=HealthResponse)
def ready(db: Session = Depends(get_db)) -> HealthResponse:
    try:
        check_db_ready(db)
        return HealthResponse(status="ready")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database not ready: {exc}") from exc


@router.get("/overview", response_model=OverviewStats)
def overview(db: Session = Depends(get_db)) -> OverviewStats:
    last = db.scalar(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1))
    return OverviewStats(
        drugs=db.scalar(select(func.count()).select_from(Drug)) or 0,
        label_versions=db.scalar(select(func.count()).select_from(LabelVersion)) or 0,
        sections=db.scalar(select(func.count()).select_from(DocumentSection)) or 0,
        chunks=db.scalar(select(func.count()).select_from(DocumentChunk)) or 0,
        last_ingestion=IngestionRunOut.model_validate(last) if last else None,
    )


@router.get("/drugs", response_model=list[DrugOut])
def list_drugs(
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[Drug]:
    stmt = select(Drug).order_by(Drug.name)
    if q:
        stmt = stmt.where(Drug.name.ilike(f"%{q}%"))
    return list(db.scalars(stmt).all())


@router.get("/drugs/{drug_id}", response_model=DrugDetailOut)
def get_drug(drug_id: str, db: Session = Depends(get_db)) -> DrugDetailOut:
    drug = db.scalar(
        select(Drug)
        .where(Drug.id == drug_id)
        .options(selectinload(Drug.labels).selectinload(DrugLabel.versions))
    )
    if not drug:
        raise HTTPException(status_code=404, detail="Drug not found")
    labels = []
    for label in drug.labels:
        labels.append(
            {
                "id": label.id,
                "set_id": label.set_id,
                "title": label.title,
                "labeler": label.labeler,
                "source_url": label.source_url,
                "versions": [
                    LabelVersionOut.model_validate(v).model_dump() for v in label.versions
                ],
            }
        )
    return DrugDetailOut(
        id=drug.id,
        name=drug.name,
        generic_name=drug.generic_name,
        created_at=drug.created_at,
        labels=labels,
    )


@router.get("/drugs/{drug_id}/versions", response_model=list[LabelVersionOut])
def list_versions(drug_id: str, db: Session = Depends(get_db)) -> list[LabelVersion]:
    drug = db.get(Drug, drug_id)
    if not drug:
        raise HTTPException(status_code=404, detail="Drug not found")
    stmt = (
        select(LabelVersion)
        .join(DrugLabel)
        .where(DrugLabel.drug_id == drug_id)
        .order_by(LabelVersion.spl_version.desc())
    )
    return list(db.scalars(stmt).all())


@router.get("/labels/{set_id}/sections")
def list_sections(
    set_id: str,
    spl_version: int = Query(...),
    db: Session = Depends(get_db),
) -> list[dict]:
    version = db.scalar(
        select(LabelVersion).where(
            LabelVersion.set_id == set_id,
            LabelVersion.spl_version == spl_version,
        )
    )
    if not version:
        raise HTTPException(status_code=404, detail="Label version not found")
    sections = db.scalars(
        select(DocumentSection)
        .where(DocumentSection.label_version_id == version.id)
        .order_by(DocumentSection.ordinal)
    ).all()
    return [
        {
            "id": s.id,
            "section_loinc": s.section_loinc,
            "section_title": s.section_title,
            "display_name": s.display_name,
            "ordinal": s.ordinal,
            "text_content": s.text_content,
            "text_hash": s.text_hash,
        }
        for s in sections
    ]


@router.post(
    "/ingestion/run",
    response_model=IngestionRunOut,
    dependencies=[Depends(require_admin)],
)
def run_ingestion(payload: IngestionRequest, db: Session = Depends(get_db)) -> IngestionRun:
    if not payload.drug_name and not payload.set_id:
        raise HTTPException(status_code=422, detail="drug_name or set_id required")
    service = IngestionService(db)
    try:
        run = service.run(
            drug_name=payload.drug_name,
            set_id=payload.set_id,
            versions=payload.versions,
            max_versions=payload.max_versions,
            ingest_latest_only=payload.ingest_latest_only,
        )
    finally:
        service.close()

    if payload.index_after_ingest and run.status == "completed" and run.set_id:
        _index_set(db, run.set_id)
        db.refresh(run)
    return run


@router.get("/ingestion/runs", response_model=list[IngestionRunOut])
def list_ingestion_runs(db: Session = Depends(get_db)) -> list[IngestionRun]:
    return list(
        db.scalars(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(50)).all()
    )


@router.post("/retrieval/search", response_model=RetrievalResponse)
def retrieval_search(payload: RetrievalRequest, db: Session = Depends(get_db)) -> RetrievalResponse:
    _ensure_version(db, payload.set_id, payload.spl_version)
    service = RetrievalService(db)
    passages, query = service.search(
        question=payload.question,
        set_id=payload.set_id,
        spl_version=payload.spl_version,
        mode=payload.mode,
        top_k=payload.top_k,
    )
    return RetrievalResponse(
        query_id=query.id if query else None,
        passages=[PassageOut(**p.__dict__) for p in passages],
        latency_ms=query.latency_ms if query else None,
    )


@router.post("/compare", response_model=CompareResponse)
def compare_labels(payload: CompareRequest, db: Session = Depends(get_db)) -> CompareResponse:
    try:
        result = compare_versions(
            db,
            set_id=payload.set_id,
            left_version=payload.left_version,
            right_version=payload.right_version,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CompareResponse(**comparison_to_dict(result))


@router.get("/compare/{comparison_id}", response_model=CompareResponse)
def get_compare(comparison_id: str) -> CompareResponse:
    result = get_comparison(comparison_id)
    if not result:
        raise HTTPException(status_code=404, detail="Comparison not found")
    return CompareResponse(**comparison_to_dict(result))


@router.get("/evaluations/datasets", response_model=list[EvaluationDatasetOut])
def list_evaluation_datasets(db: Session = Depends(get_db)) -> list[EvaluationDatasetOut]:
    ensure_builtin_datasets(db)
    rows = list(
        db.scalars(select(EvaluationDataset).order_by(EvaluationDataset.created_at.desc())).all()
    )
    return [
        EvaluationDatasetOut(
            id=r.id,
            name=r.name,
            version=r.version,
            description=r.description,
            is_synthetic=r.is_synthetic,
            item_count=len(r.items or []),
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post(
    "/evaluations/run",
    response_model=EvaluationRunOut,
    dependencies=[Depends(require_admin)],
)
def evaluations_run(
    payload: EvaluationRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> EvaluationRun:
    """Start an evaluation asynchronously and return the running record immediately.

    Gemini-backed generation can take well over a minute; waiting synchronously
    caused proxy/UI timeouts that looked like a broken Run button.
    """
    ensure_builtin_datasets(db)
    dataset_id = payload.dataset_id
    if not dataset_id:
        if not payload.dataset_name or not payload.dataset_version:
            raise HTTPException(
                status_code=422,
                detail="dataset_id or (dataset_name + dataset_version) required",
            )
        dataset = db.scalar(
            select(EvaluationDataset).where(
                EvaluationDataset.name == payload.dataset_name,
                EvaluationDataset.version == payload.dataset_version,
            )
        )
        if not dataset:
            raise HTTPException(status_code=404, detail="Evaluation dataset not found")
        dataset_id = dataset.id
    try:
        run = create_evaluation_run(
            db,
            dataset_id=dataset_id,
            retrieval_mode=payload.retrieval_mode,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    background_tasks.add_task(
        _execute_evaluation_job,
        run_id=run.id,
        dataset_id=dataset_id,
        retrieval_mode=payload.retrieval_mode,
        top_k=payload.top_k,
        run_generation=payload.run_generation,
        log_to_mlflow=payload.log_to_mlflow,
    )
    return run


@router.get("/evaluations", response_model=list[EvaluationRunOut])
def list_evaluations(db: Session = Depends(get_db)) -> list[EvaluationRun]:
    expire_stale_evaluation_runs(db)
    return list(
        db.scalars(select(EvaluationRun).order_by(EvaluationRun.started_at.desc()).limit(50)).all()
    )


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationRunOut)
def get_evaluation(evaluation_id: str, db: Session = Depends(get_db)) -> EvaluationRun:
    run = db.get(EvaluationRun, evaluation_id)
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return run


@router.get("/models")
def list_models(db: Session = Depends(get_db)) -> list[dict]:
    return list_registered_pipelines(db)


@router.get("/models/{version}")
def get_model(version: str, db: Session = Depends(get_db)) -> dict:
    row = get_pipeline(db, version)
    if not row:
        raise HTTPException(status_code=404, detail="Pipeline version not found")
    return row


@router.post("/models/register", dependencies=[Depends(require_admin)])
def register_model(payload: ModelRegisterRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return register_from_evaluation(db, evaluation_run_id=payload.evaluation_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MLflow registration failed: {exc}") from exc


@router.post("/models/promote", dependencies=[Depends(require_admin)])
def promote_model(payload: ModelPromoteRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return promote_pipeline(
            db,
            candidate_pipeline_id=payload.pipeline_id,
            min_recall_at_5=payload.min_recall_at_5,
            min_citation_validity=payload.min_citation_validity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Promotion failed: {exc}") from exc


@router.post("/models/rollback", dependencies=[Depends(require_admin)])
def rollback_model(db: Session = Depends(get_db)) -> dict:
    try:
        return rollback_pipeline(db)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Rollback failed: {exc}") from exc


@router.post("/rag/answer", response_model=RagAnswerOut)
def rag_answer(payload: RagRequest, db: Session = Depends(get_db)) -> RagAnswerOut:
    _ensure_version(db, payload.set_id, payload.spl_version)
    answer = RagService(db).answer(
        question=payload.question,
        set_id=payload.set_id,
        spl_version=payload.spl_version,
        mode=payload.mode,
        top_k=payload.top_k,
    )
    # Reload citations
    db.refresh(answer)
    citations = [
        {
            "passage_id": c.passage_id,
            "set_id": c.set_id,
            "spl_version": c.spl_version,
            "section_title": c.section_title,
            "evidence_text": c.evidence_text,
            "citation_valid": c.citation_valid,
        }
        for c in answer.citations
    ]
    return RagAnswerOut(
        id=answer.id,
        question=answer.question,
        answer_text=answer.answer_text,
        abstained=answer.abstained,
        model_identifier=answer.model_identifier,
        pipeline_version=answer.pipeline_version,
        prompt_template_version=answer.prompt_template_version,
        referenced_versions=answer.referenced_versions,
        retrieval_config=answer.retrieval_config,
        latency_ms=answer.latency_ms,
        citations=citations,
    )


def _ensure_version(db: Session, set_id: str, spl_version: int) -> LabelVersion:
    version = db.scalar(
        select(LabelVersion).where(
            LabelVersion.set_id == set_id,
            LabelVersion.spl_version == spl_version,
        )
    )
    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Label version unavailable: set_id={set_id} version={spl_version}",
        )
    return version


def _index_set(db: Session, set_id: str) -> None:
    versions = db.scalars(select(LabelVersion).where(LabelVersion.set_id == set_id)).all()
    for version in versions:
        sections = list(
            db.scalars(
                select(DocumentSection).where(DocumentSection.label_version_id == version.id)
            ).all()
        )
        drafts = build_chunks_for_version(version, sections)
        chunks = persist_chunks(db, version, drafts)
        embed_chunks_for_version(db, chunks)
