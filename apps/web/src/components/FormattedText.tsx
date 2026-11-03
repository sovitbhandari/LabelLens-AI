import type { ReactNode } from "react";

const BULLET_RE = /^\s*(?:[-*•]|\d+[.)])\s+/;

function normalizeListNewlines(text: string): string {
  // Force jammed inline bullets onto their own lines without breaking phrases like "dose-related".
  let out = text.replace(/\r\n/g, "\n");
  // Mid-line bullet glyphs from SPL text ("… side • 40 mg …")
  out = out.replace(/\s+[•]\s+/g, "\n• ");
  // DailyMed often embeds sub-bullets as "o Item"
  out = out.replace(/\s+o\s+(?=[A-Z(])/g, "\n- ");
  out = out.replace(/([:;])\s+((?:[-*•]|\d+[.)])\s+)/g, "$1\n$2");
  // Between consecutive list markers on one line: "- a - b" or "1. a 2. b"
  for (let i = 0; i < 4; i += 1) {
    const next = out.replace(
      /((?:^|\n)\s*(?:[-*•]|\d+[.)])\s+[^\n]*?)\s+((?:[-*•]|\d+[.)])\s+)/g,
      "$1\n$2",
    );
    if (next === out) break;
    out = next;
  }
  return out.trim();
}

function linkify(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  const combined =
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|(https?:\/\/[^\s<>"'`)\]}]+)/g;
  let match: RegExpExecArray | null;
  while ((match = combined.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }
    if (match[1] && match[2]) {
      nodes.push(
        <a
          key={`${keyPrefix}-md-${match.index}`}
          href={match[2]}
          target="_blank"
          rel="noreferrer"
          className="break-all font-medium text-aqua-700 underline decoration-aqua-300 underline-offset-2"
        >
          {match[1]}
        </a>,
      );
    } else {
      const full = match[3] ?? match[0];
      const href = full.replace(/[.,;:!?)]+$/, "");
      const trailing = full.slice(href.length);
      nodes.push(
        <a
          key={`${keyPrefix}-url-${match.index}`}
          href={href}
          target="_blank"
          rel="noreferrer"
          className="break-all font-medium text-aqua-700 underline decoration-aqua-300 underline-offset-2"
        >
          {href}
        </a>,
      );
      if (trailing) nodes.push(trailing);
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

type Block =
  | { type: "p"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] };

function toBlocks(text: string): Block[] {
  const normalized = normalizeListNewlines(text);
  const chunks = normalized.split(/\n{2,}/);
  const blocks: Block[] = [];

  for (const chunk of chunks) {
    const lines = chunk
      .split("\n")
      .map((l) => l.trimEnd())
      .filter((l) => l.trim().length > 0);

    if (lines.length === 0) continue;

    const allBullets = lines.every((l) => BULLET_RE.test(l));
    if (allBullets && lines.length > 0) {
      const ordered = lines.every((l) => /^\s*\d+[.)]\s+/.test(l));
      const items = lines.map((l) => l.replace(BULLET_RE, "").trim());
      blocks.push({ type: ordered ? "ol" : "ul", items });
      continue;
    }

    // Mixed: peel leading prose, then list lines
    const prose: string[] = [];
    const list: string[] = [];
    let hitList = false;
    for (const line of lines) {
      if (BULLET_RE.test(line)) {
        hitList = true;
        list.push(line);
      } else if (!hitList) {
        prose.push(line);
      } else {
        // continuation of previous list item
        if (list.length) {
          list[list.length - 1] = `${list[list.length - 1]} ${line.trim()}`;
        } else {
          prose.push(line);
        }
      }
    }
    if (prose.length) {
      blocks.push({ type: "p", text: prose.join("\n") });
    }
    if (list.length) {
      const ordered = list.every((l) => /^\s*\d+[.)]\s+/.test(l));
      blocks.push({
        type: ordered ? "ol" : "ul",
        items: list.map((l) => l.replace(BULLET_RE, "").trim()),
      });
    }
  }

  return blocks;
}

export function dailyMedUrl(setId: string, splVersion?: number | null): string {
  if (splVersion != null) {
    return `https://dailymed.nlm.nih.gov/dailymed/versionInfo.cfm?setid=${setId}&version=${splVersion}`;
  }
  return `https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=${setId}`;
}

export default function FormattedText({
  text,
  className = "",
}: {
  text: string;
  className?: string;
}) {
  const blocks = toBlocks(normalizeListNewlines(text));

  return (
    <div className={`space-y-3 text-sm leading-7 text-ink-900 ${className}`}>
      {blocks.map((block, i) => {
        if (block.type === "p") {
          return (
            <p key={i} className="whitespace-pre-wrap">
              {linkify(block.text, `p${i}`)}
            </p>
          );
        }
        const ListTag = block.type === "ol" ? "ol" : "ul";
        return (
          <ListTag
            key={i}
            className={
              block.type === "ol"
                ? "list-decimal space-y-2 pl-5"
                : "list-disc space-y-2 pl-5"
            }
          >
            {block.items.map((item, j) => (
              <li key={j}>{linkify(item, `l${i}-${j}`)}</li>
            ))}
          </ListTag>
        );
      })}
    </div>
  );
}
