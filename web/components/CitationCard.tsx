"use client";

import type { ChunkUsed } from "../lib/types";
import { jurisdictionFlag } from "../lib/jurisdiction";

interface CitationCardProps {
  chunk: ChunkUsed;
  onOpen: (chunk: ChunkUsed) => void;
}

export default function CitationCard({ chunk, onOpen }: CitationCardProps) {
  return (
    <button
      type="button"
      onClick={() => onOpen(chunk)}
      className="group inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs transition-colors hover:border-teal hover:bg-teal-light"
    >
      <span aria-hidden className="text-sm leading-none">
        {jurisdictionFlag(chunk.jurisdiction)}
      </span>
      <span className="font-medium text-slate-700 group-hover:text-teal-dark">{chunk.instrument_short}</span>
      <span className="text-slate-300">·</span>
      <span className="text-slate-500 group-hover:text-teal-dark">{chunk.section_ref}</span>
    </button>
  );
}
