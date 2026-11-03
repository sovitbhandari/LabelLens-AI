# Engineering Decision Log

## 2026-11-02 — Direct SDK RAG, not LangChain

**Decision:** Implement retrieval and generation with SQLAlchemy, pgvector, Sentence Transformers, and the OpenAI SDK directly.

**Why:** Portfolio clarity, unit-testability of RRF/citation logic, and avoidance of opaque orchestration layers.

## 2026-11-02 — Immutable label versions

**Decision:** After ingestion, a `(set_id, spl_version)` row is immutable. Content-hash mismatch raises a provenance flag instead of overwriting.

**Why:** Regulatory/document research requires trustworthy historical provenance.

## 2026-11-02 — Historical versions via DailyMed ZIP

**Decision:** Current XML from `/spls/{SETID}.xml`; older versions from `getFile.cfm?type=zip&setid=&version=`.

**Why:** Confirmed against live DailyMed API; `/spls/{SETID}.xml` only returns the latest published SPL for that set ID.

## 2026-11-02 — Local Sentence Transformers default

**Decision:** Default embeddings = `all-MiniLM-L6-v2` (384-d). OpenAI embeddings optional and isolated by model/dimension.

**Why:** Reproducible local demos without API spend; dimension mismatch must not share indexes.

## 2026-11-02 — Deterministic diffs for comparison

**Decision:** `difflib`-based section alignment is source of truth; LLM may only summarize observed diffs.

**Why:** Prevents fabricated regulatory/medical change claims.

## 2026-11-02 — Exact vs ANN vector search

**Decision:** Start with exact cosine similarity (`<=>` / distance ops) for small corpora; add IVFFlat/HNSW only after measuring latency vs recall.

**Why:** ANN can hurt recall on small collections; measure before approximating.
