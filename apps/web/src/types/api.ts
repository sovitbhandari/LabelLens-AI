export type Drug = {
  id: string;
  name: string;
  generic_name: string | null;
  created_at: string;
};

export type LabelVersion = {
  id: string;
  set_id: string;
  spl_version: number;
  published_date: string | null;
  source_url: string;
  content_sha256: string;
  provenance_flag: string | null;
  ingested_at: string;
};

export type OverviewStats = {
  drugs: number;
  label_versions: number;
  sections: number;
  chunks: number;
  last_ingestion: {
    id: string;
    status: string;
    set_id: string | null;
    versions_ingested: number;
    sections_ingested: number;
    started_at: string;
    finished_at: string | null;
    error_message: string | null;
  } | null;
};

export type Passage = {
  chunk_id: string;
  passage_id: string;
  set_id: string;
  spl_version: number;
  section_title: string | null;
  text_content: string;
  score: number;
  rank: number;
  sources: Record<string, unknown>;
};

export type Citation = {
  passage_id: string;
  set_id: string;
  spl_version: number;
  section_title: string | null;
  evidence_text: string;
  citation_valid: boolean;
};

export type RagAnswer = {
  id: string;
  question: string;
  answer_text: string;
  abstained: boolean;
  model_identifier: string;
  pipeline_version: string;
  prompt_template_version: string;
  referenced_versions: string[] | null;
  retrieval_config: Record<string, unknown> | null;
  latency_ms: number | null;
  citations: Citation[];
};

export type EvaluationDataset = {
  id: string;
  name: string;
  version: string;
  description: string | null;
  is_synthetic: boolean;
  item_count: number;
  created_at: string;
};

export type EvaluationRun = {
  id: string;
  dataset_id: string;
  pipeline_configuration_id: string | null;
  retrieval_mode: string;
  status: string;
  metrics: Record<string, unknown> | null;
  failure_cases: unknown[] | null;
  mlflow_run_id: string | null;
  started_at: string;
  finished_at: string | null;
};

export type PipelineModel = {
  id: string;
  name: string;
  version: string;
  alias: string | null;
  embedding_model: string;
  embedding_dimension: number;
  retrieval_strategy: string;
  top_k: number;
  rrf_k: number;
  llm_model: string;
  prompt_template_version: string;
  mlflow_model_version: string | null;
  config_json: { metrics?: Record<string, number> } | null;
  created_at: string | null;
  is_champion: boolean;
};

export type CompareResult = {
  id: string;
  set_id: string;
  left_version: number;
  right_version: number;
  sections_compared: number;
  added: number;
  removed: number;
  modified: number;
  formatting_only: number;
  unchanged: number;
  summary: string;
  created_at: string;
  diffs: Array<{
    section_key: string;
    left_title: string | null;
    right_title: string | null;
    change_type: string;
    left_text: string;
    right_text: string;
    added_spans: string[];
    removed_spans: string[];
  }>;
};
