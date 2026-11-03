# LabelLens AI — Progress Log

**Author:** Sovit Bhandari

## Status overview

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 0 — Repo & architecture | **Complete** | Monorepo, docs, env, compose files |
| Phase 1 — Backend & ingestion | **Complete** | Real DailyMed Lipitor v7+v8 ingested |
| Phase 2 — Retrieval & RAG | **Complete** | Keyword/vector/hybrid + citations verified |
| Phase 3 — Historical comparison | **Complete** | Deterministic diffs; Lipitor v7→v8 measured |
| Phase 4 — MLflow & evaluation | **Complete (local file store)** | Real Lipitor eval executed; register + promote verified |
| Phase 5 — Frontend | **Complete** | All six pages wired to live API |
| Phase 6 — Integration & deploy | **Mostly complete** | CI, e2e pass; Docker DB start still flaky; AWS skeleton only |

## Foundation checkpoint — PASSED

Real Lipitor SPL (`set_id=a60cc18b-0631-4cf0-b021-9f52224ece65`): ingest → chunk → embed → retrieve → cite.

## Evaluation evidence (executed 2026-11-02)

Author-curated Lipitor dataset (`labellens-lipitor-author-curated` v1) — **not independently third-party validated**.

| Mode | recall@5 | MRR | version_filter_accuracy | citation_validity |
|------|----------|-----|-------------------------|-------------------|
| keyword | 0.50 | 0.50 | 1.0 | 1.0 |
| vector | 0.75 | 0.75 | 1.0 | 1.0 |
| hybrid | 0.75 | 0.75 | 1.0 | 1.0 |

Abstention correctness ≈ 0.25 with evidence-only fallback (no OpenAI key): answerable items also abstain. This is expected and recorded honestly.

MLflow file store (`file:./mlruns`):
- Logged evaluation runs
- Registered `labellens-rag-pipeline` model version 1 as candidate then **promoted to champion**

## Frontend e2e — PASSED

```text
npx playwright test
✓ document selection, ask with citations, and version compare
```

## Verification commands

```text
poetry run ruff check app tests     # passed
poetry run pytest -q                # 21 passed
npm run typecheck && npm run build  # passed
npx playwright test                 # 1 passed
scripts/run_eval_and_promote.py     # eval + register + promote executed
```

## Remaining limitations

1. Without `GEMINI_API_KEY` / `OPENAI_API_KEY` → generative synthesis uses evidence-only abstention
2. Docker Compose Postgres container start hung on this host (Homebrew Postgres used)
3. AWS configs are skeletons only — **not deployed**
4. Rollback requires a second successful promotion to create `previous_champion`
5. Evaluation Lab dataset for Lipitor is author-curated, not independent clinical review

## Local URLs

- Web: http://127.0.0.1:5173
- API: http://127.0.0.1:8000/docs
