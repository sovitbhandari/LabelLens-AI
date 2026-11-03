import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../services/api";

const ADMIN = import.meta.env.VITE_ADMIN_TOKEN ?? "dev-admin-token-change-me";

export default function ModelsPage() {
  const qc = useQueryClient();
  const modelsQuery = useQuery({ queryKey: ["models"], queryFn: api.models });
  const runsQuery = useQuery({ queryKey: ["eval-runs"], queryFn: api.evaluations });
  const [message, setMessage] = useState<string>("");

  const registerMutation = useMutation({
    mutationFn: (evaluationRunId: string) =>
      api.registerModel({ evaluation_run_id: evaluationRunId }, ADMIN),
    onSuccess: (res) => {
      setMessage(`Registered mlflow v${res.mlflow_model_version} as ${res.alias}`);
      qc.invalidateQueries({ queryKey: ["models"] });
    },
    onError: (err) => setMessage((err as Error).message),
  });

  const promoteMutation = useMutation({
    mutationFn: (pipelineId: string) =>
      api.promoteModel(
        { pipeline_id: pipelineId, min_recall_at_5: 0.3, min_citation_validity: 0.5 },
        ADMIN,
      ),
    onSuccess: (res) => {
      setMessage(res.reason || (res.promoted ? "Promoted" : "Rejected"));
      qc.invalidateQueries({ queryKey: ["models"] });
    },
    onError: (err) => setMessage((err as Error).message),
  });

  const rollbackMutation = useMutation({
    mutationFn: () => api.rollbackModel(ADMIN),
    onSuccess: (res) => {
      setMessage(
        res.rolled_back
          ? `Rolled back to champion v${res.champion}`
          : res.reason || "Rollback unavailable",
      );
      qc.invalidateQueries({ queryKey: ["models"] });
    },
    onError: (err) => setMessage((err as Error).message),
  });

  const completedRuns = (runsQuery.data ?? []).filter((r) => r.status === "completed");

  return (
    <section className="ll-fade space-y-6">
      <div>
        <p className="ll-kicker">Pipeline governance</p>
        <h1 className="ll-title">Model Registry</h1>
        <p className="ll-subtitle">
          Candidate and champion aliases with explicit promote / rollback confirmation.
        </p>
      </div>

      <div className="ll-panel-strong p-5">
        <h2 className="font-display text-xl font-semibold text-ink-950">
          Register from evaluation
        </h2>
        {completedRuns.length === 0 ? (
          <p className="mt-2 text-sm text-ink-500">
            No completed evaluation runs. Run one in Evaluation Lab first.
          </p>
        ) : (
          <ul className="mt-4 space-y-2">
            {completedRuns.slice(0, 8).map((run) => (
              <li
                key={run.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-white/80 px-3 py-2.5 text-sm"
              >
                <span>
                  {run.retrieval_mode} · recall{" "}
                  {Number(run.metrics?.recall_at_5 ?? 0).toFixed(2)} · {run.id.slice(0, 8)}
                </span>
                <button
                  type="button"
                  className="ll-btn-ink"
                  onClick={() => {
                    if (confirm("Register this evaluation pipeline as candidate?")) {
                      registerMutation.mutate(run.id);
                    }
                  }}
                >
                  Register candidate
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {message && (
        <p className="rounded-2xl border border-aqua-300/50 bg-aqua-100/70 px-4 py-3 text-sm text-aqua-700">
          {message}
        </p>
      )}

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-display text-2xl font-semibold text-ink-950">
            Registered pipelines
          </h2>
          <button
            type="button"
            className="rounded-xl border border-coral-500/40 bg-coral-100 px-3 py-1.5 text-sm font-semibold text-coral-700"
            onClick={() => {
              if (confirm("Roll back champion to previous_champion?")) {
                rollbackMutation.mutate();
              }
            }}
          >
            Rollback champion
          </button>
        </div>

        {(modelsQuery.data ?? []).length === 0 && (
          <p className="text-sm text-ink-500">No pipeline configurations registered yet.</p>
        )}

        {(modelsQuery.data ?? []).map((m, i) => (
          <article
            key={m.id}
            className="ll-panel overflow-hidden"
            style={{ animationDelay: `${i * 40}ms` }}
          >
            <div className="ll-stat-band h-1.5" />
            <div className="p-5 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-display text-lg font-semibold text-ink-950">
                  {m.name} · {m.version}
                </h3>
                {m.alias && (
                  <span className="rounded-lg bg-aqua-100 px-2 py-0.5 text-xs font-semibold uppercase text-aqua-700">
                    {m.alias}
                  </span>
                )}
                {m.is_champion && (
                  <span className="rounded-lg bg-gradient-to-r from-gold-500 to-coral-500 px-2 py-0.5 text-xs font-semibold uppercase text-white">
                    champion
                  </span>
                )}
              </div>
              <dl className="mt-4 grid gap-3 md:grid-cols-3">
                <Meta label="Retrieval" value={`${m.retrieval_strategy} · top_k=${m.top_k}`} />
                <Meta
                  label="Embedding"
                  value={`${m.embedding_model} (${m.embedding_dimension}d)`}
                />
                <Meta label="MLflow version" value={m.mlflow_model_version ?? "—"} />
              </dl>
              {m.config_json?.metrics && (
                <pre className="mt-4 overflow-auto rounded-xl bg-paper-100/80 p-3 text-xs">
                  {JSON.stringify(m.config_json.metrics, null, 2)}
                </pre>
              )}
              {m.alias === "candidate" && m.mlflow_model_version && (
                <button
                  type="button"
                  className="ll-btn-primary mt-4"
                  onClick={() => {
                    if (
                      confirm(
                        "Promote this candidate to champion? Requires recall/citation thresholds.",
                      )
                    ) {
                      promoteMutation.mutate(m.id);
                    }
                  }}
                >
                  Promote to champion
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-white/75 p-3">
      <dt className="text-xs uppercase tracking-[0.14em] text-ink-500">{label}</dt>
      <dd className="mt-1 break-all font-medium text-ink-950">{value}</dd>
    </div>
  );
}
