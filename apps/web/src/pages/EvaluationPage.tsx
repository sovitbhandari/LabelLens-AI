import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../services/api";

const ADMIN = import.meta.env.VITE_ADMIN_TOKEN ?? "dev-admin-token-change-me";
const BAR_COLORS = ["#0e8fa3", "#e85d3a", "#e8a820", "#3f9a63", "#18b4c9", "#c2412b"];

function formatApiError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (parsed.detail != null) return JSON.stringify(parsed.detail);
  } catch {
    // not JSON
  }
  if (raw.includes("UniqueViolation") || raw.includes("uq_pipeline_configs_name_version")) {
    return "Evaluation failed while saving pipeline metadata (duplicate version). Retry the run.";
  }
  return raw.length > 400 ? `${raw.slice(0, 400)}…` : raw;
}

export default function EvaluationPage() {
  const qc = useQueryClient();
  const datasetsQuery = useQuery({
    queryKey: ["eval-datasets"],
    queryFn: api.evaluationDatasets,
  });
  const runsQuery = useQuery({
    queryKey: ["eval-runs"],
    queryFn: api.evaluations,
  });

  const [datasetId, setDatasetId] = useState("");
  const [mode, setMode] = useState<"keyword" | "vector" | "hybrid">("hybrid");
  const [runGeneration, setRunGeneration] = useState(true);
  const [selectedRunId, setSelectedRunId] = useState<string>("");

  useEffect(() => {
    if (!datasetId && datasetsQuery.data?.[0]) setDatasetId(datasetsQuery.data[0].id);
  }, [datasetsQuery.data, datasetId]);

  const hasRunning = useMemo(
    () => (runsQuery.data ?? []).some((r) => r.status === "running"),
    [runsQuery.data],
  );

  useEffect(() => {
    if (!hasRunning) return;
    const timer = window.setInterval(() => {
      void qc.invalidateQueries({ queryKey: ["eval-runs"] });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [hasRunning, qc]);

  const runMutation = useMutation({
    mutationFn: () =>
      api.runEvaluation(
        {
          dataset_id: datasetId,
          retrieval_mode: mode,
          top_k: 5,
          run_generation: runGeneration,
          log_to_mlflow: true,
        },
        ADMIN,
      ),
    onSuccess: (run) => {
      setSelectedRunId(run.id);
      qc.invalidateQueries({ queryKey: ["eval-runs"] });
    },
  });

  const selected = useMemo(() => {
    const runs = runsQuery.data ?? [];
    return runs.find((r) => r.id === selectedRunId) ?? runs[0] ?? null;
  }, [runsQuery.data, selectedRunId]);

  const chartData = useMemo(() => {
    if (!selected?.metrics) return [];
    const m = selected.metrics;
    return [
      { name: "Recall@5", value: Number(m.recall_at_5 ?? 0) },
      { name: "MRR", value: Number(m.mrr ?? 0) },
      { name: "Precision@5", value: Number(m.precision_at_5 ?? 0) },
      { name: "Version OK", value: Number(m.version_filter_accuracy ?? 0) },
      { name: "Citation", value: Number(m.citation_validity ?? 0) },
      { name: "Abstention", value: Number(m.abstention_correctness ?? 0) },
    ];
  }, [selected]);

  const busy = runMutation.isPending || hasRunning;

  return (
    <section className="ll-fade space-y-6">
      <div>
        <p className="ll-kicker">Reproducible experiments</p>
        <h1 className="ll-title">Evaluation Lab</h1>
        <p className="ll-subtitle">
          Run versioned datasets across retrieval strategies. Charts reflect executed metrics — not
          placeholders. With Gemini generation enabled, a full Lipitor run usually takes 1–2 minutes.
        </p>
      </div>

      <div className="ll-panel grid gap-4 p-5 md:grid-cols-4">
        <label className="text-sm md:col-span-1">
          <span className="font-medium text-ink-500">Dataset</span>
          <select
            className="ll-input"
            value={datasetId}
            onChange={(e) => setDatasetId(e.target.value)}
          >
            {(datasetsQuery.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} {d.version}
                {d.is_synthetic ? " (synthetic)" : ""} · {d.item_count} items
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="font-medium text-ink-500">Retrieval strategy</span>
          <select
            className="ll-input"
            value={mode}
            onChange={(e) => setMode(e.target.value as typeof mode)}
          >
            <option value="hybrid">Hybrid</option>
            <option value="keyword">Keyword</option>
            <option value="vector">Vector</option>
          </select>
        </label>
        <label className="flex items-end gap-2 text-sm pb-2">
          <input
            type="checkbox"
            className="size-4 accent-aqua-600"
            checked={runGeneration}
            onChange={(e) => setRunGeneration(e.target.checked)}
          />
          <span className="font-medium text-ink-700">Include LLM generation</span>
        </label>
        <div className="flex items-end">
          <button
            type="button"
            disabled={!datasetId || busy}
            onClick={() => runMutation.mutate()}
            className="ll-btn-primary w-full disabled:opacity-60"
          >
            {busy ? "Evaluation running…" : "Run evaluation"}
          </button>
        </div>
      </div>

      {runMutation.error && (
        <p className="text-sm text-coral-700">{formatApiError(runMutation.error)}</p>
      )}
      {hasRunning && (
        <p className="rounded-xl border border-aqua-300/50 bg-aqua-100/60 px-4 py-3 text-sm text-aqua-700">
          Evaluation is running in the background. Metrics will appear here when the run completes.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <aside className="space-y-2">
          <h2 className="text-sm font-semibold text-ink-950">Past runs</h2>
          {(runsQuery.data ?? []).length === 0 && (
            <p className="text-sm text-ink-500">No evaluation runs yet.</p>
          )}
          {(runsQuery.data ?? []).map((run) => (
            <button
              key={run.id}
              type="button"
              onClick={() => setSelectedRunId(run.id)}
              className={`block w-full rounded-2xl border px-3 py-3 text-left text-sm transition ${
                selected?.id === run.id
                  ? "border-coral-400 bg-gradient-to-br from-coral-100 to-white"
                  : "border-white/70 bg-white/70 hover:bg-aqua-100/50"
              }`}
            >
              <div className="font-semibold text-ink-950">
                {run.retrieval_mode} · {run.status}
              </div>
              <div className="mt-1 text-xs text-ink-500">{run.started_at}</div>
            </button>
          ))}
        </aside>

        <div className="space-y-4">
          {!selected ? (
            <p className="text-sm text-ink-500">Select or run an evaluation to inspect metrics.</p>
          ) : selected.status === "running" ? (
            <div className="ll-panel-strong p-5">
              <h2 className="font-display text-2xl font-semibold text-ink-950">Running…</h2>
              <p className="mt-2 text-sm text-ink-700">
                Retrieving and scoring dataset items
                {runGeneration ? " with Gemini generation" : ""}. This page refreshes automatically.
              </p>
            </div>
          ) : selected.status === "failed" ? (
            <div className="ll-panel p-5 border border-coral-500/30">
              <h2 className="font-display text-2xl font-semibold text-coral-700">Run failed</h2>
              <pre className="mt-3 whitespace-pre-wrap rounded-xl bg-coral-100/50 p-3 text-xs text-coral-700">
                {JSON.stringify(selected.failure_cases ?? [], null, 2)}
              </pre>
            </div>
          ) : (
            <>
              <div className="ll-panel-strong p-5">
                <h2 className="font-display text-2xl font-semibold text-ink-950">Metrics</h2>
                <p className="mt-1 text-xs text-ink-500">
                  run {selected.id}
                  {selected.mlflow_run_id ? ` · mlflow ${selected.mlflow_run_id}` : ""}
                </p>
                <div className="mt-4 h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#cfe9ef" />
                      <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#2a4a63" }} />
                      <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: "#2a4a63" }} />
                      <Tooltip />
                      <Bar dataKey="value" radius={[8, 8, 0, 0]}>
                        {chartData.map((_, index) => (
                          <Cell key={index} fill={BAR_COLORS[index % BAR_COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="ll-panel p-5">
                <h3 className="font-display text-xl font-semibold text-ink-950">Failure cases</h3>
                {(selected.failure_cases ?? []).length === 0 ? (
                  <p className="mt-2 text-sm text-ink-500">No failure cases recorded.</p>
                ) : (
                  <ul className="mt-3 space-y-2 text-sm text-ink-700">
                    {(selected.failure_cases ?? []).slice(0, 20).map((f, idx) => (
                      <li key={idx} className="rounded-xl bg-gold-100/50 p-3">
                        <pre className="whitespace-pre-wrap text-xs">
                          {JSON.stringify(f, null, 2)}
                        </pre>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
