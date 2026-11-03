#!/usr/bin/env python3
"""Run Lipitor evaluation, register candidate, promote to champion, smoke rollback."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.pop("HF_TOKEN", None)
os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
os.chdir(ROOT / "apps" / "api")

from sqlalchemy import select

from app.core.logging import configure_logging, get_logger
from app.db.base import SessionLocal
from app.evaluation.runner import ensure_builtin_datasets, run_evaluation
from app.mlops.registry import promote_pipeline, register_from_evaluation, rollback_pipeline
from app.models.entities import EvaluationDataset


def main() -> int:
    configure_logging()
    log = get_logger("eval_promote")
    db = SessionLocal()
    try:
        ensure_builtin_datasets(db)
        dataset = db.scalar(
            select(EvaluationDataset).where(
                EvaluationDataset.name == "labellens-lipitor-author-curated",
                EvaluationDataset.version == "v1",
            )
        )
        if not dataset:
            log.error("lipitor_dataset_missing")
            return 1

        results = []
        for mode in ("keyword", "vector", "hybrid"):
            run = run_evaluation(
                db,
                dataset_id=dataset.id,
                retrieval_mode=mode,  # type: ignore[arg-type]
                top_k=5,
                run_generation=True,
                log_to_mlflow=True,
            )
            metrics = {
                k: v
                for k, v in (run.metrics or {}).items()
                if isinstance(v, (int, float))
            }
            log.info("eval_done", mode=mode, status=run.status, metrics=metrics)
            results.append(run)
            print(f"\n=== EVAL {mode} status={run.status} ===")
            print(metrics)

        best = max(
            results,
            key=lambda r: float((r.metrics or {}).get("recall_at_5") or 0.0),
        )
        registered = register_from_evaluation(db, evaluation_run_id=best.id)
        print("\n=== REGISTERED ===")
        print(registered)

        promoted = promote_pipeline(
            db,
            candidate_pipeline_id=registered["pipeline_id"],
            min_recall_at_5=0.25,
            min_citation_validity=0.5,
        )
        print("\n=== PROMOTE ===")
        print(promoted)

        # Promote a second non-regressing pipeline so previous_champion exists, then rollback.
        others = [
            r
            for r in results
            if r.id != best.id
            and float((r.metrics or {}).get("recall_at_5") or 0.0)
            >= float((best.metrics or {}).get("recall_at_5") or 0.0)
        ]
        if others:
            second = register_from_evaluation(db, evaluation_run_id=others[0].id)
            second_promo = promote_pipeline(
                db,
                candidate_pipeline_id=second["pipeline_id"],
                min_recall_at_5=0.25,
                min_citation_validity=0.5,
            )
            print("\n=== SECOND PROMOTE ===")
            print(second_promo)
            rolled = rollback_pipeline(db)
            print("\n=== ROLLBACK ===")
            print(rolled)
        else:
            print("\n=== ROLLBACK ===")
            print({"rolled_back": False, "reason": "No non-regressing second candidate available"})
        return 0 if best.status == "completed" else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
