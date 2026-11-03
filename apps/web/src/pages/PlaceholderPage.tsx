export default function PlaceholderPage({
  title,
  body,
}: {
  title: string;
  body: string;
}) {
  return (
    <section className="rounded-xl border border-dashed border-ink-900/20 bg-paper-50 p-8">
      <h1 className="font-display text-3xl font-semibold text-ink-950">{title}</h1>
      <p className="mt-3 max-w-2xl text-sm leading-7 text-ink-700">{body}</p>
      <p className="mt-4 text-xs uppercase tracking-[0.16em] text-ink-500">
        Honest unavailable state — not fabricated UI metrics
      </p>
    </section>
  );
}
