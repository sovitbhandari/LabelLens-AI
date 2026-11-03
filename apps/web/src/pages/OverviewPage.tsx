import { useQuery } from "@tanstack/react-query";
import { api } from "../services/api";

const tones = [
  "from-aqua-500 to-aqua-600",
  "from-coral-500 to-coral-600",
  "from-gold-500 to-gold-600",
  "from-moss-500 to-moss-600",
];

export default function OverviewPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
  });

  if (isLoading) return <StatusPanel title="Loading system overview…" />;
  if (error) {
    return (
      <StatusPanel title="Backend unavailable" body={(error as Error).message} tone="error" />
    );
  }
  if (!data) {
    return <StatusPanel title="No overview data yet" body="Ingest a DailyMed label to begin." />;
  }

  const cards = [
    { label: "Indexed drugs", value: data.drugs },
    { label: "Label versions", value: data.label_versions },
    { label: "Sections", value: data.sections },
    { label: "Chunks", value: data.chunks },
  ];

  return (
    <section className="ll-fade space-y-8">
      <div>
        <p className="ll-kicker">Live corpus</p>
        <h1 className="ll-title">Overview</h1>
        <p className="ll-subtitle">
          Real counts from PostgreSQL — provenance, versions, and indexed passages at a glance.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card, i) => (
          <div
            key={card.label}
            className="ll-panel overflow-hidden p-0"
            style={{ animationDelay: `${i * 70}ms` }}
          >
            <div className={`h-1.5 bg-gradient-to-r ${tones[i]}`} />
            <div className="p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-500">
                {card.label}
              </p>
              <p className="mt-3 font-display text-4xl font-bold text-ink-950">{card.value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="ll-panel-strong p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-2xl font-semibold text-ink-950">Last ingestion</h2>
          {data.last_ingestion && (
            <span className="rounded-lg bg-moss-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-moss-600">
              {data.last_ingestion.status}
            </span>
          )}
        </div>
        {!data.last_ingestion ? (
          <p className="mt-3 text-sm text-ink-700">No ingestion runs recorded yet.</p>
        ) : (
          <dl className="mt-4 grid gap-4 text-sm md:grid-cols-2">
            <Meta label="Set ID" value={data.last_ingestion.set_id ?? "—"} />
            <Meta
              label="Versions / sections"
              value={`${data.last_ingestion.versions_ingested} / ${data.last_ingestion.sections_ingested}`}
            />
            <Meta label="Started" value={data.last_ingestion.started_at} />
            {data.last_ingestion.error_message && (
              <Meta label="Error" value={data.last_ingestion.error_message} danger />
            )}
          </dl>
        )}
      </div>
    </section>
  );
}

function Meta({
  label,
  value,
  danger,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div className="rounded-xl bg-white/70 p-3">
      <dt className="text-xs uppercase tracking-[0.14em] text-ink-500">{label}</dt>
      <dd className={`mt-1 break-all font-medium ${danger ? "text-coral-700" : "text-ink-950"}`}>
        {value}
      </dd>
    </div>
  );
}

function StatusPanel({
  title,
  body,
  tone = "neutral",
}: {
  title: string;
  body?: string;
  tone?: "neutral" | "error";
}) {
  return (
    <div
      className={`ll-fade rounded-2xl border p-6 ${
        tone === "error"
          ? "border-coral-500/30 bg-coral-100 text-coral-700"
          : "border-white/70 bg-white/70 text-ink-700"
      }`}
    >
      <h1 className="font-display text-2xl text-ink-950">{title}</h1>
      {body && <p className="mt-2 whitespace-pre-wrap text-sm">{body}</p>}
    </div>
  );
}
