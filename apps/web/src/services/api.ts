import type {
  CompareResult,
  Drug,
  EvaluationDataset,
  EvaluationRun,
  LabelVersion,
  OverviewStats,
  Passage,
  PipelineModel,
  RagAnswer,
} from "../types/api";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  overview: () => request<OverviewStats>("/api/overview"),
  drugs: (q?: string) =>
    request<Drug[]>(`/api/drugs${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  drugVersions: (drugId: string) =>
    request<LabelVersion[]>(`/api/drugs/${drugId}/versions`),
  sections: (setId: string, splVersion: number) =>
    request<
      Array<{
        id: string;
        section_loinc: string | null;
        section_title: string | null;
        text_content: string;
      }>
    >(`/api/labels/${setId}/sections?spl_version=${splVersion}`),
  search: (body: {
    question: string;
    set_id: string;
    spl_version: number;
    mode: "keyword" | "vector" | "hybrid";
    top_k?: number;
  }) =>
    request<{ query_id: string | null; passages: Passage[]; latency_ms: number | null }>(
      "/api/retrieval/search",
      { method: "POST", body: JSON.stringify(body) },
    ),
  answer: (body: {
    question: string;
    set_id: string;
    spl_version: number;
    mode: "keyword" | "vector" | "hybrid";
    top_k?: number;
  }) =>
    request<RagAnswer>("/api/rag/answer", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  compare: (body: { set_id: string; left_version: number; right_version: number }) =>
    request<CompareResult>("/api/compare", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  evaluationDatasets: () => request<EvaluationDataset[]>("/api/evaluations/datasets"),
  evaluations: () => request<EvaluationRun[]>("/api/evaluations"),
  evaluation: (id: string) => request<EvaluationRun>(`/api/evaluations/${id}`),
  runEvaluation: (
    body: {
      dataset_id?: string;
      dataset_name?: string;
      dataset_version?: string;
      retrieval_mode: "keyword" | "vector" | "hybrid";
      top_k?: number;
      run_generation?: boolean;
      log_to_mlflow?: boolean;
    },
    adminToken: string,
  ) =>
    request<EvaluationRun>("/api/evaluations/run", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "X-Admin-Token": adminToken },
    }),
  models: () => request<PipelineModel[]>("/api/models"),
  registerModel: (body: { evaluation_run_id: string }, adminToken: string) =>
    request<{
      pipeline_id: string;
      mlflow_model_version: string;
      alias: string | null;
    }>("/api/models/register", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "X-Admin-Token": adminToken },
    }),
  promoteModel: (
    body: {
      pipeline_id: string;
      min_recall_at_5?: number;
      min_citation_validity?: number;
    },
    adminToken: string,
  ) =>
    request<{ promoted: boolean; reason: string }>("/api/models/promote", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "X-Admin-Token": adminToken },
    }),
  rollbackModel: (adminToken: string) =>
    request<{ rolled_back: boolean; champion?: string; reason?: string }>(
      "/api/models/rollback",
      {
        method: "POST",
        headers: { "X-Admin-Token": adminToken },
      },
    ),
};
