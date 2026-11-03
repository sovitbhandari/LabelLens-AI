import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import FormattedText, { dailyMedUrl } from "../components/FormattedText";
import { api } from "../services/api";

export default function ExplorerPage() {
  const [q, setQ] = useState("Lipitor");
  const [selectedDrug, setSelectedDrug] = useState<string>("");
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);

  const drugsQuery = useQuery({
    queryKey: ["drugs", q],
    queryFn: () => api.drugs(q),
  });

  const versionsQuery = useQuery({
    queryKey: ["versions", selectedDrug],
    queryFn: () => api.drugVersions(selectedDrug),
    enabled: Boolean(selectedDrug),
  });

  const activeVersion = useMemo(() => {
    const versions = versionsQuery.data ?? [];
    if (selectedVersion == null) return versions[0] ?? null;
    return versions.find((v) => v.spl_version === selectedVersion) ?? null;
  }, [versionsQuery.data, selectedVersion]);

  const sectionsQuery = useQuery({
    queryKey: ["sections", activeVersion?.set_id, activeVersion?.spl_version],
    queryFn: () => api.sections(activeVersion!.set_id, activeVersion!.spl_version),
    enabled: Boolean(activeVersion),
  });

  return (
    <section className="ll-fade space-y-6">
      <div>
        <p className="ll-kicker">Browse provenance</p>
        <h1 className="ll-title">Document Explorer</h1>
        <p className="ll-subtitle">
          Search ingested DailyMed labels, flip versions, and inspect official sections with source
          links.
        </p>
      </div>

      <input
        className="ll-input max-w-xl"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search drugs"
      />

      {drugsQuery.isLoading && <p className="text-sm text-ink-500">Loading drugs…</p>}
      {drugsQuery.error && (
        <p className="text-sm text-coral-700">{(drugsQuery.error as Error).message}</p>
      )}

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        <aside className="space-y-2">
          {(drugsQuery.data ?? []).map((drug, i) => (
            <button
              key={drug.id}
              type="button"
              style={{ animationDelay: `${i * 40}ms` }}
              onClick={() => {
                setSelectedDrug(drug.id);
                setSelectedVersion(null);
              }}
              className={`ll-fade block w-full rounded-2xl border px-4 py-3 text-left transition ${
                selectedDrug === drug.id
                  ? "border-aqua-500 bg-gradient-to-br from-aqua-100 to-white shadow-soft"
                  : "border-white/70 bg-white/65 hover:border-coral-300 hover:bg-coral-100/40"
              }`}
            >
              <div className="font-semibold text-ink-950">{drug.name}</div>
              <div className="mt-1 text-xs text-ink-500">{drug.generic_name ?? "—"}</div>
            </button>
          ))}
          {!drugsQuery.isLoading && (drugsQuery.data?.length ?? 0) === 0 && (
            <p className="text-sm text-ink-500">No indexed drugs match this search.</p>
          )}
        </aside>

        <div className="space-y-4">
          {versionsQuery.data && versionsQuery.data.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {versionsQuery.data.map((v) => (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => setSelectedVersion(v.spl_version)}
                  className={`rounded-xl px-3 py-1.5 text-sm font-medium transition ${
                    activeVersion?.spl_version === v.spl_version
                      ? "bg-gradient-to-r from-coral-600 to-gold-500 text-white"
                      : "bg-white/80 text-ink-700 hover:bg-gold-100"
                  }`}
                >
                  v{v.spl_version}
                  {v.published_date ? ` · ${v.published_date}` : ""}
                </button>
              ))}
            </div>
          )}

          {activeVersion && (
            <div className="ll-panel-strong p-5 text-sm">
              <p>
                <span className="text-ink-500">SET ID:</span>{" "}
                <span className="font-medium text-ink-950">{activeVersion.set_id}</span>
              </p>
              <p className="mt-2">
                <span className="text-ink-500">DailyMed:</span>{" "}
                <a
                  className="font-medium text-aqua-700 underline decoration-aqua-300 underline-offset-2"
                  href={dailyMedUrl(activeVersion.set_id, activeVersion.spl_version)}
                  target="_blank"
                  rel="noreferrer"
                >
                  View label v{activeVersion.spl_version} on DailyMed
                </a>
              </p>
              <p className="mt-2 break-all">
                <span className="text-ink-500">Ingest source:</span>{" "}
                <a
                  className="font-medium text-aqua-700 underline decoration-aqua-300 underline-offset-2"
                  href={activeVersion.source_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {activeVersion.source_url}
                </a>
              </p>
              <p className="mt-2 break-all">
                <span className="text-ink-500">SHA-256:</span> {activeVersion.content_sha256}
              </p>
            </div>
          )}

          {sectionsQuery.isLoading && <p className="text-sm text-ink-500">Loading sections…</p>}
          {sectionsQuery.data?.map((section, i) => (
            <article
              key={section.id}
              className="ll-panel overflow-hidden"
              style={{ animationDelay: `${i * 30}ms` }}
            >
              <div className="h-1 bg-gradient-to-r from-aqua-500 via-coral-500 to-gold-500" />
              <div className="p-5">
                <h2 className="font-display text-xl font-semibold text-ink-950">
                  {section.section_title ?? "Untitled section"}
                </h2>
                <p className="mt-1 text-xs font-medium uppercase tracking-[0.14em] text-aqua-700">
                  {section.section_loinc ?? "no LOINC"}
                </p>
                <div className="mt-3 text-ink-700">
                  <FormattedText
                    text={
                      section.text_content.slice(0, 1200) +
                      (section.text_content.length > 1200 ? "…" : "")
                    }
                  />
                </div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
