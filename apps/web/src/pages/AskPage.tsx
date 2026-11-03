import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import FormattedText, { dailyMedUrl } from "../components/FormattedText";
import { api } from "../services/api";
import type { RagAnswer } from "../types/api";

export default function AskPage() {
  const drugsQuery = useQuery({ queryKey: ["drugs-ask"], queryFn: () => api.drugs() });
  const [drugId, setDrugId] = useState("");
  const [version, setVersion] = useState<number | "">("");
  const [mode, setMode] = useState<"keyword" | "vector" | "hybrid">("hybrid");
  const [question, setQuestion] = useState("What are the contraindications for Lipitor?");
  const [answer, setAnswer] = useState<RagAnswer | null>(null);

  const versionsQuery = useQuery({
    queryKey: ["ask-versions", drugId],
    queryFn: () => api.drugVersions(drugId),
    enabled: Boolean(drugId),
  });

  useEffect(() => {
    if (!drugId && drugsQuery.data?.[0]) setDrugId(drugsQuery.data[0].id);
  }, [drugsQuery.data, drugId]);

  useEffect(() => {
    if (versionsQuery.data?.[0] && version === "") {
      setVersion(versionsQuery.data[0].spl_version);
    }
  }, [versionsQuery.data, version]);

  const mutation = useMutation({
    mutationFn: async () => {
      const selected = versionsQuery.data?.find((v) => v.spl_version === version);
      if (!selected || version === "") throw new Error("Select a label version");
      return api.answer({
        question,
        set_id: selected.set_id,
        spl_version: Number(version),
        mode,
      });
    },
    onSuccess: setAnswer,
  });

  return (
    <section className="ll-fade space-y-6">
      <div>
        <p className="ll-kicker">Evidence-backed Q&A</p>
        <h1 className="ll-title">Ask LabelLens</h1>
        <p className="ll-subtitle">
          Version-scoped RAG with citation verification. Abstains when evidence is insufficient or
          when the LLM key is not configured.
        </p>
      </div>

      <div className="ll-panel grid gap-4 p-5 md:grid-cols-3">
        <label className="text-sm">
          <span className="font-medium text-ink-500">Drug</span>
          <select
            className="ll-input"
            value={drugId}
            onChange={(e) => {
              setDrugId(e.target.value);
              setVersion("");
              setAnswer(null);
            }}
          >
            <option value="">Select…</option>
            {(drugsQuery.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="font-medium text-ink-500">Version</span>
          <select
            className="ll-input"
            value={version}
            onChange={(e) => setVersion(e.target.value ? Number(e.target.value) : "")}
          >
            <option value="">Select…</option>
            {(versionsQuery.data ?? []).map((v) => (
              <option key={v.id} value={v.spl_version}>
                v{v.spl_version}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="font-medium text-ink-500">Retrieval mode</span>
          <select
            className="ll-input"
            value={mode}
            onChange={(e) => setMode(e.target.value as typeof mode)}
          >
            <option value="hybrid">Hybrid (RRF)</option>
            <option value="keyword">Keyword (FTS)</option>
            <option value="vector">Vector (pgvector)</option>
          </select>
        </label>
      </div>

      <textarea
        className="ll-input min-h-32"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
      />

      <button
        type="button"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
        className="ll-btn-primary disabled:opacity-60"
      >
        {mutation.isPending ? "Retrieving…" : "Ask LabelLens"}
      </button>

      {mutation.error && (
        <p className="text-sm text-coral-700">{(mutation.error as Error).message}</p>
      )}

      {answer && (
        <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          <article className="ll-panel-strong p-6">
            <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">
              <span>{answer.model_identifier}</span>
              <span className="text-aqua-500">·</span>
              <span>pipeline {answer.pipeline_version}</span>
              {answer.abstained && (
                <span className="rounded-lg bg-gold-100 px-2 py-0.5 text-gold-600">Abstained</span>
              )}
            </div>
            <div className="mt-4">
              <FormattedText text={answer.answer_text} />
            </div>
          </article>
          <aside className="space-y-3">
            <h2 className="font-display text-xl font-semibold text-ink-950">Evidence</h2>
            {answer.citations.length === 0 && (
              <p className="text-sm text-ink-500">No validated citations returned.</p>
            )}
            {answer.citations.map((c, i) => (
              <div
                key={c.passage_id}
                className="ll-panel overflow-hidden"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                <div className="h-1 bg-gradient-to-r from-aqua-500 to-coral-500" />
                <div className="p-4">
                  <p className="text-xs font-medium text-aqua-700">{c.passage_id}</p>
                  <p className="mt-1 text-sm font-semibold text-ink-950">
                    {c.section_title ?? "Section"}
                  </p>
                  <a
                    className="mt-1 inline-block text-xs font-medium text-aqua-700 underline decoration-aqua-300 underline-offset-2"
                    href={dailyMedUrl(c.set_id, c.spl_version)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open DailyMed v{c.spl_version}
                  </a>
                  <div className="mt-2 text-ink-700">
                    <FormattedText text={c.evidence_text.slice(0, 500)} />
                  </div>
                </div>
              </div>
            ))}
          </aside>
        </div>
      )}
    </section>
  );
}
