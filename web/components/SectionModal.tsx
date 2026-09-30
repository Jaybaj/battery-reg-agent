"use client";

import { useEffect, useState } from "react";
import type { ChunkUsed } from "../lib/types";
import { fetchSection, type SectionDetail } from "../lib/api";
import { jurisdictionFlag } from "../lib/jurisdiction";
import { parseSectionText } from "../lib/sectionText";

interface SectionModalProps {
  chunk: ChunkUsed;
  onClose: () => void;
}

function sourceLinkLabel(url: string): string {
  let host = "";
  try {
    host = new URL(url).hostname;
  } catch {
    // Malformed URL -- fall through to the generic label.
  }
  if (host.endsWith("eur-lex.europa.eu")) return "View on EUR-Lex";
  if (host.endsWith("ecfr.gov")) return "View on eCFR";
  return "View official source";
}

// Width of the clause-marker column, and the indent per nesting level -- the
// same value, so a nested marker lines up with its parent clause's text.
const MARKER_COLUMN_REM = 2.25;

function SectionBody({ section }: { section: SectionDetail }) {
  const paragraphs = parseSectionText(section.text, section.parent_context);

  return (
    <div className="space-y-4 text-sm leading-[1.7] text-slate-700">
      {paragraphs.map((lines, paragraphIndex) => (
        <div key={paragraphIndex} className="space-y-2">
          {lines.map((line, lineIndex) => {
            const indentRem = (line.depth + (line.alignWithClauseText ? 1 : 0)) * MARKER_COLUMN_REM;
            return (
              <div key={lineIndex} className="flex" style={{ paddingLeft: `${indentRem}rem` }}>
                {line.marker && (
                  <span
                    className="shrink-0 pr-2 font-medium tabular-nums text-slate-500"
                    style={{ minWidth: `${MARKER_COLUMN_REM}rem` }}
                  >
                    {line.marker}
                  </span>
                )}
                <p className="min-w-0 flex-1">{line.text}</p>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function Spinner() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-sm text-slate-500" role="status">
      <span className="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-teal" aria-hidden />
      Loading full section text…
    </div>
  );
}

export default function SectionModal({ chunk, onClose }: SectionModalProps) {
  const [section, setSection] = useState<SectionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    fetchSection(chunk.instrument, chunk.section_ref)
      .then((data) => {
        if (!cancelled) setSection(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [chunk.instrument, chunk.section_ref]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-900/30 [animation:fade-in_0.2s_ease-out]"
      onClick={onClose}
    >
      <div
        className="flex h-full w-full max-w-md flex-col overflow-hidden bg-white shadow-2xl [animation:slide-in-right_0.25s_ease-out]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-500">
              <span aria-hidden>{jurisdictionFlag(chunk.jurisdiction)}</span>
              {chunk.instrument_short}
            </div>
            <h2 className="mt-1 text-base font-semibold text-slate-900">
              {chunk.section_ref}
              {section?.section_title ? ` — ${section.section_title}` : ""}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          >
            ✕
          </button>
        </div>

        <div className="overflow-y-auto px-6 py-5">
          {loading && <Spinner />}
          {error && <p className="text-sm text-red-600">{error}</p>}
          {section && (
            <>
              <SectionBody section={section} />
              <a
                href={section.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-6 inline-block text-sm font-medium text-teal underline decoration-teal/40 underline-offset-2 hover:text-teal-dark"
              >
                {sourceLinkLabel(section.url)} ↗
              </a>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
