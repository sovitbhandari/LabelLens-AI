import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import FormattedText from "../components/FormattedText";
import { api } from "../services/api";
import type { CompareResult } from "../types/api";

export default function ComparePage() {
  const drugsQuery = useQuery({ queryKey: ["drugs-compare"], queryFn: () => api.drugs() });
  const [drugId, setDrugId] = useState("");
  const [left, setLeft] = useState<number | "">("");
  const [right, setRight] = useState<number | "">("");
  const [result, setResult] = useState<CompareResult | null>(null);

  const versionsQuery = useQuery({
    queryKey: ["compare-versions", drugId],
    queryFn: () => api.drugVersions(drugId),
    enabled: Boolean(drugId),
  });

  useEffect(() => {
    if (!drugId && drugsQuery.data?.[0]) setDrugId(drugsQuery.data[0].id);
  }, [drugsQuery.data, drugId]);

  useEffect(() => {
    const versions = versionsQuery.data ?? [];
    if (versions.length >= 2 && left === "" && right === "") {
      setRight(versions[0].spl_version);
      setLeft(versions[1].spl_version);
    }
  }, [versionsQuery.data, left, right]);

  const mutation = useMutation({
    mutationFn: async () => {
      const selected = versionsQuery.data?.[0];
      if (!selected || left === "" || right === "") throw new Error("Select two versions");
      return api.compare({
        set_id: selected.set_id,
        left_version: Number(left),
        right_version: Number(right),
      });
    },
    onSuccess: setResult,
  });

  return (
    <section className="ll-fade space-y-6">
      <div>
        <p className="ll-kicker">Historical diff engine</p>
        <h1 className="ll-title">Version Comparison</h1>
        <p className="ll-subtitle">
          Deterministic section diffs are the source of truth. Formatting-only changes are never
          described as medical or regulatory changes.
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
              setLeft("");
              setRight("");
              setResult(null);
            }}
          >
            {(drugsQuery.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="font-medium text-ink-500">Left version</span>
          <select
            className="ll-input"
            value={left}
            onChange={(e) => setLeft(Number(e.target.value))}
          >
            {(versionsQuery.data ?? []).map((v) => (
              <option key={`l-${v.id}`} value={v.spl_version}>
                v{v.spl_version}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="font-medium text-ink-500">Right version</span>
          <select
            className="ll-input"
            value={right}
            onChange={(e) => setRight(Number(e.target.value))}
          >
            {(versionsQuery.data ?? []).map((v) => (
              <option key={`r-${v.id}`} value={v.spl_version}>
                v{v.spl_version}
              </option>
            ))}
          </select>
        </label>
      </div>

      <button
        type="button"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
        className="ll-btn-coral disabled:opacity-60"
      >
        {mutation.isPending ? "Comparing…" : "Compare versions"}
      </button>

      {mutation.error && (
        <p className="text-sm text-coral-700">{(mutation.error as Error).message}</p>
      )}

      {result && (
        <div className="space-y-4">
          <div className="ll-panel-strong p-6">
            <p className="text-sm font-medium text-ink-500">
              v{result.left_version} → v{result.right_version} · {result.sections_compared} sections
            </p>
            <div className="mt-4 flex flex-wrap gap-2 text-sm">
              <Stat label="Modified" value={result.modified} tone="coral" />
              <Stat label="Added" value={result.added} tone="moss" />
              <Stat label="Removed" value={result.removed} tone="gold" />
              <Stat label="Formatting only" value={result.formatting_only} tone="aqua" />
              <Stat label="Unchanged" value={result.unchanged} tone="ink" />
            </div>
            <div className="mt-5 rounded-xl bg-white/80 p-4 text-ink-800">
              <FormattedText text={result.summary} />
            </div>
          </div>

          {result.diffs.map((diff) => (
            <article
              key={`${diff.section_key}-${diff.change_type}-${diff.left_title}-${diff.right_title}`}
              className="ll-panel overflow-hidden"
            >
              <div
                className={`h-1.5 ${
                  diff.change_type === "added"
                    ? "bg-moss-500"
                    : diff.change_type === "removed"
                      ? "bg-coral-500"
                      : "bg-gold-500"
                }`}
              />
              <div className="p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-lg bg-ink-900 px-2 py-0.5 text-xs uppercase text-white">
                    {diff.change_type}
                  </span>
                  <h2 className="font-display text-lg font-semibold text-ink-950">
                    {diff.right_title || diff.left_title || diff.section_key}
                  </h2>
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <div className="rounded-xl bg-coral-100/50 p-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-coral-700">
                      Left
                    </p>
                    <p className="mt-2 whitespace-pre-wrap text-sm text-ink-700">
                      {diff.left_text.slice(0, 900) || "—"}
                    </p>
                  </div>
                  <div className="rounded-xl bg-aqua-100/60 p-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-aqua-700">
                      Right
                    </p>
                    <p className="mt-2 whitespace-pre-wrap text-sm text-ink-700">
                      {diff.right_text.slice(0, 900) || "—"}
                    </p>
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "coral" | "moss" | "gold" | "aqua" | "ink";
}) {
  const tones = {
    coral: "bg-coral-100 text-coral-700",
    moss: "bg-moss-100 text-moss-600",
    gold: "bg-gold-100 text-gold-600",
    aqua: "bg-aqua-100 text-aqua-700",
    ink: "bg-paper-200 text-ink-800",
  };
  return (
    <span className={`rounded-xl px-3 py-1.5 ${tones[tone]}`}>
      {label}: <strong>{value}</strong>
    </span>
  );
}
