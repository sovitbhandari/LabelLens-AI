# LabelLens AI — Architecture

## Product problem

Pharmaceutical labeling documents change over time. Researchers need version-aware retrieval, evidence-backed answers, and deterministic historical diffs — not a generic PDF chatbot.

## System context

```mermaid
flowchart LR
  User[Researcher / Dashboard] --> Web[React Web]
  Web --> API[FastAPI]
  API --> PG[(PostgreSQL + pgvector)]
  API --> DM[DailyMed API]
  API --> EMB[Sentence Transformers / OpenAI Embeddings]
  API --> LLM[OpenAI LLM]
  API --> MLF[MLflow Tracking + Registry]
```

## Data flow — ingestion

```mermaid
sequenceDiagram
  participant API
  participant DM as DailyMed
  participant DB as PostgreSQL
  API->>DM: search / history / XML or ZIP
  DM-->>API: SPL metadata + document
  API->>API: parse sections, checksum
  API->>DB: upsert drug/label; insert immutable version
  Note over DB: hash mismatch on existing version = flag, never overwrite
```

## Data flow — RAG

```mermaid
flowchart TD
  Q[Question + version filter] --> KW[FTS keyword retrieval]
  Q --> VEC[pgvector dense retrieval]
  KW --> RRF[Reciprocal Rank Fusion]
  VEC --> RRF
  RRF --> GEN[Structured LLM generation]
  GEN --> CITE[Citation verification]
  CITE --> OUT[Answer or abstain]
```

## Version isolation rule

Retrieval never crosses label versions unless the caller explicitly requests comparison or cross-version analysis. Every chunk references exact `(set_id, spl_version, section_id)`.

## Key design decisions

See [decision-log.md](./decision-log.md).
