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
      className="group flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-xs shadow-sm transition-colors hover:border-emerald-300 hover:bg-emerald-50"
    >
      <span aria-hidden className="text-base leading-none">
        {jurisdictionFlag(chunk.jurisdiction)}
      </span>
      <span className="flex flex-col leading-tight">
        <span className="font-medium text-slate-800 group-hover:text-emerald-900">
          {chunk.instrument_short}
        </span>
        <span className="text-slate-500 group-hover:text-emerald-700">{chunk.section_ref}</span>
      </span>
    </button>
  );
}
