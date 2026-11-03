"""Model registry listing and registration orchestration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.mlops.tracking import (
    configure_mlflow,
    get_alias_version,
    promote_candidate,
    rollback_to_previous,
    set_alias,
)
from app.models.entities import EvaluationRun, PipelineConfiguration

logger = get_logger(__name__)


def list_registered_pipelines(db: Session) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(PipelineConfiguration).order_by(PipelineConfiguration.created_at.desc())
        ).all()
    )
    champion = get_alias_version("champion")
    candidate = get_alias_version("candidate")
    previous = get_alias_version("previous_champion")
    out: list[dict[str, Any]] = []
    for row in rows:
        alias = row.alias
        if row.mlflow_model_version and champion and row.mlflow_model_version == champion:
            alias = "champion"
        elif row.mlflow_model_version and candidate and row.mlflow_model_version == candidate:
            alias = "candidate"
        out.append(
            {
                "id": row.id,
                "name": row.name,
                "version": row.version,
                "alias": alias,
                "embedding_model": row.embedding_model,
                "embedding_dimension": row.embedding_dimension,
                "retrieval_strategy": row.retrieval_strategy,
                "top_k": row.top_k,
                "rrf_k": row.rrf_k,
                "llm_model": row.llm_model,
                "prompt_template_version": row.prompt_template_version,
                "mlflow_model_version": row.mlflow_model_version,
                "config_json": row.config_json,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "is_champion": alias == "champion"
                or (row.mlflow_model_version is not None and row.mlflow_model_version == champion),
                "mlflow_aliases": {
                    "champion": champion,
                    "candidate": candidate,
                    "previous_champion": previous,
                },
            }
        )
    return out


def get_pipeline(db: Session, version: str) -> dict[str, Any] | None:
    row = db.scalar(
        select(PipelineConfiguration).where(PipelineConfiguration.version == version)
    )
    if not row:
        row = db.get(PipelineConfiguration, version)
    if not row:
        row = db.scalar(
            select(PipelineConfiguration).where(
                PipelineConfiguration.mlflow_model_version == version
            )
        )
    if not row:
        return None
    items = list_registered_pipelines(db)
    return next((i for i in items if i["id"] == row.id), None)


def register_from_evaluation(
    db: Session,
    *,
    evaluation_run_id: str,
    set_candidate_alias: bool = True,
) -> dict[str, Any]:
    import mlflow
    from mlflow.tracking import MlflowClient

    run = db.get(EvaluationRun, evaluation_run_id)
    if not run or run.status != "completed":
        raise ValueError("Completed evaluation run required")
    pipeline = (
        db.get(PipelineConfiguration, run.pipeline_configuration_id)
        if run.pipeline_configuration_id
        else None
    )
    if not pipeline:
        raise ValueError("Evaluation run has no pipeline configuration")

    metrics = {k: float(v) for k, v in (run.metrics or {}).items() if isinstance(v, (int, float))}
    settings = get_settings()
    configure_mlflow(settings)

    payload = {
        "pipeline_version": pipeline.version,
        "embedding_model": pipeline.embedding_model,
        "embedding_dimension": pipeline.embedding_dimension,
        "chunk_size": pipeline.chunk_size,
        "chunk_overlap": pipeline.chunk_overlap,
        "retrieval_strategy": pipeline.retrieval_strategy,
        "top_k": pipeline.top_k,
        "rrf_k": pipeline.rrf_k,
        "llm_model": pipeline.llm_model,
        "prompt_template_version": pipeline.prompt_template_version,
        "metrics": metrics,
        "evaluation_run_id": run.id,
        "dataset": (pipeline.config_json or {}).get("dataset"),
    }

    with mlflow.start_run() as active:
        mlflow.log_params(
            {
                k: str(v)[:250]
                for k, v in payload.items()
                if k != "metrics" and v is not None
            }
        )
        mlflow.log_metrics(metrics)
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "pipeline_config.json"
            artifact.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            mlflow.log_artifact(str(artifact), artifact_path="pipeline")
        mlflow_run_id = active.info.run_id

    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    name = settings.mlflow_registered_model_name
    try:
        client.create_registered_model(name)
    except Exception:
        pass
    source = f"runs:/{mlflow_run_id}/pipeline"
    mv = client.create_model_version(name=name, source=source, run_id=mlflow_run_id)
    model_version = str(mv.version)

    pipeline.mlflow_model_version = model_version
    if set_candidate_alias:
        set_alias(model_version, "candidate")
        pipeline.alias = "candidate"
    run.mlflow_run_id = run.mlflow_run_id or mlflow_run_id
    db.commit()
    db.refresh(pipeline)
    logger.info(
        "pipeline_registered_from_eval",
        pipeline_id=pipeline.id,
        mlflow_version=model_version,
    )
    return {
        "pipeline_id": pipeline.id,
        "pipeline_version": pipeline.version,
        "mlflow_run_id": mlflow_run_id,
        "mlflow_model_version": model_version,
        "alias": pipeline.alias,
        "metrics": metrics,
    }


def promote_pipeline(
    db: Session,
    *,
    candidate_pipeline_id: str,
    min_recall_at_5: float = 0.3,
    min_citation_validity: float = 0.9,
) -> dict[str, Any]:
    candidate = db.get(PipelineConfiguration, candidate_pipeline_id)
    if not candidate or not candidate.mlflow_model_version:
        raise ValueError("Candidate pipeline with mlflow_model_version required")
    cand_metrics = (candidate.config_json or {}).get("metrics") or {}
    cand_metrics = {k: float(v) for k, v in cand_metrics.items() if isinstance(v, (int, float))}

    champion_version = get_alias_version("champion")
    champion_metrics = None
    if champion_version:
        champ = db.scalar(
            select(PipelineConfiguration).where(
                PipelineConfiguration.mlflow_model_version == champion_version
            )
        )
        if champ and champ.config_json:
            champion_metrics = {
                k: float(v)
                for k, v in (champ.config_json.get("metrics") or {}).items()
                if isinstance(v, (int, float))
            }

    decision = promote_candidate(
        candidate_version=candidate.mlflow_model_version,
        metrics=cand_metrics,
        champion_metrics=champion_metrics,
        min_recall_at_5=min_recall_at_5,
        min_citation_validity=min_citation_validity,
        apply_aliases=True,
    )
    if decision["promoted"]:
        for row in db.scalars(select(PipelineConfiguration)).all():
            if row.alias == "champion":
                row.alias = "previous_champion"
        candidate.alias = "champion"
        db.commit()
    decision["pipeline_id"] = candidate.id
    decision["metrics"] = cand_metrics
    decision["champion_metrics"] = champion_metrics
    return decision


def rollback_pipeline(db: Session) -> dict[str, Any]:
    result = rollback_to_previous()
    if result.get("rolled_back"):
        new_champion = result["champion"]
        demoted = result.get("demoted_to_candidate")
        for row in db.scalars(select(PipelineConfiguration)).all():
            if row.mlflow_model_version == new_champion:
                row.alias = "champion"
            elif demoted and row.mlflow_model_version == demoted:
                row.alias = "candidate"
        db.commit()
    return result
