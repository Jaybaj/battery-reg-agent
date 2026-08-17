"use client";

import { useEffect, useState } from "react";
import type { ChunkUsed } from "../lib/types";
import { fetchSection, type SectionDetail } from "../lib/api";
import { jurisdictionFlag } from "../lib/jurisdiction";

interface SectionModalProps {
  chunk: ChunkUsed;
  onClose: () => void;
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

        <div className="overflow-y-auto px-5 py-4">
          {loading && <p className="text-sm text-slate-500">Loading full section text…</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
          {section && (
            <>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{section.text}</p>
              <a
                href={section.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-4 inline-block text-sm font-medium text-teal underline decoration-teal/40 underline-offset-2 hover:text-teal-dark"
              >
                View official source ↗
              </a>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
