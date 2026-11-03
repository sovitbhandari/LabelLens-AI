"""MLflow experiment tracking and pipeline registry helpers."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _mlflow():
    import mlflow

    return mlflow


def configure_mlflow(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    mlflow = _mlflow()
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment_name)


def log_evaluation_run(
    *,
    params: dict[str, Any],
    metrics: dict[str, float],
    tags: dict[str, str] | None = None,
    artifacts: dict[str, str] | None = None,
) -> str:
    """Log an evaluation run. Returns MLflow run id."""
    settings = get_settings()
    configure_mlflow(settings)
    mlflow = _mlflow()
    with mlflow.start_run() as run:
        mlflow.log_params({k: str(v)[:250] for k, v in params.items()})
        mlflow.log_metrics(metrics)
        if tags:
            mlflow.set_tags(tags)
        if artifacts:
            for local_path, artifact_path in artifacts.items():
                mlflow.log_artifact(local_path, artifact_path)
        run_id = run.info.run_id
    logger.info("mlflow_run_logged", run_id=run_id, metrics=metrics)
    return run_id


def register_pipeline(
    *,
    run_id: str,
    model_name: str | None = None,
    tags: dict[str, str] | None = None,
) -> str:
    """Register a pipeline configuration artifact as an MLflow model version."""
    settings = get_settings()
    configure_mlflow(settings)
    mlflow = _mlflow()
    name = model_name or settings.mlflow_registered_model_name
    # Register a lightweight python model flavor pointing at the run
    model_uri = f"runs:/{run_id}/pipeline"
    try:
        result = mlflow.register_model(model_uri, name)
        version = str(result.version)
    except Exception:
        # Fallback: create registered model version via client if artifact missing
        from mlflow.tracking import MlflowClient

        client = MlflowClient()
        try:
            client.create_registered_model(name)
        except Exception:
            pass
        mv = client.create_model_version(name=name, source=f"runs:/{run_id}", run_id=run_id)
        version = str(mv.version)
    if tags:
        from mlflow.tracking import MlflowClient

        client = MlflowClient()
        for k, v in tags.items():
            client.set_model_version_tag(name, version, k, v)
    logger.info("pipeline_registered", name=name, version=version, run_id=run_id)
    return version


def set_alias(version: str, alias: str, model_name: str | None = None) -> None:
    settings = get_settings()
    name = model_name or settings.mlflow_registered_model_name
    from mlflow.tracking import MlflowClient

    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    client.set_registered_model_alias(name, alias, version)
    logger.info("alias_set", name=name, version=version, alias=alias)


def get_alias_version(alias: str, model_name: str | None = None) -> str | None:
    settings = get_settings()
    name = model_name or settings.mlflow_registered_model_name
    from mlflow.tracking import MlflowClient

    try:
        client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
        mv = client.get_model_version_by_alias(name, alias)
        return str(mv.version)
    except Exception as exc:
        logger.warning("alias_lookup_failed", alias=alias, error=str(exc))
        return None


def promote_candidate(
    *,
    candidate_version: str,
    metrics: dict[str, float],
    champion_metrics: dict[str, float] | None,
    min_recall_at_5: float = 0.3,
    min_citation_validity: float = 0.9,
    apply_aliases: bool = True,
) -> dict[str, Any]:
    """Promote candidate to champion only if multi-metric thresholds pass.

    Decision logic is pure. Alias mutations happen only after thresholds pass
    and only when apply_aliases=True (requires a reachable MLflow server).
    """
    decision: dict[str, Any] = {
        "candidate_version": candidate_version,
        "promoted": False,
        "reason": "",
        "previous_champion": None,
    }
    if metrics.get("recall_at_5", 0.0) < min_recall_at_5:
        decision["reason"] = (
            f"Rejected: recall_at_5={metrics.get('recall_at_5')} < {min_recall_at_5}"
        )
        return decision
    if metrics.get("citation_validity", 1.0) < min_citation_validity:
        decision["reason"] = (
            f"Rejected: citation_validity={metrics.get('citation_validity')} "
            f"< {min_citation_validity}"
        )
        return decision
    if champion_metrics:
        # Require non-regression on recall; do not promote on a single unrelated metric win.
        if metrics.get("recall_at_5", 0.0) + 1e-9 < champion_metrics.get("recall_at_5", 0.0):
            decision["reason"] = "Rejected: recall_at_5 regresses versus champion"
            return decision
        if metrics.get("mrr", 0.0) + 1e-9 < champion_metrics.get("mrr", 0.0) - 0.05:
            decision["reason"] = "Rejected: MRR regresses beyond tolerance versus champion"
            return decision

    if not apply_aliases:
        decision["promoted"] = True
        decision["reason"] = "Promoted (dry-run): thresholds satisfied; aliases not applied"
        return decision

    prev = get_alias_version("champion")
    decision["previous_champion"] = prev
    if prev:
        set_alias(prev, "previous_champion")
    set_alias(candidate_version, "champion")
    decision["promoted"] = True
    decision["reason"] = "Promoted: thresholds satisfied and no material regression"
    return decision


def rollback_to_previous(model_name: str | None = None) -> dict[str, Any]:
    prev = get_alias_version("previous_champion", model_name=model_name)
    if not prev:
        return {"rolled_back": False, "reason": "No previous_champion alias registered"}
    current = get_alias_version("champion", model_name=model_name)
    if current:
        set_alias(current, "candidate", model_name=model_name)
    set_alias(prev, "champion", model_name=model_name)
    return {"rolled_back": True, "champion": prev, "demoted_to_candidate": current}
