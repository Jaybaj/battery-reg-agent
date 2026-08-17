"use client";

import type { JurisdictionFilter } from "../lib/types";

interface HeaderProps {
  jurisdictionFilter: JurisdictionFilter;
  onJurisdictionChange: (value: JurisdictionFilter) => void;
}

export default function Header({ jurisdictionFilter, onJurisdictionChange }: HeaderProps) {
  return (
    <header className="flex shrink-0 items-center justify-between bg-navy px-6 py-4">
      <div className="flex items-center gap-2.5">
        <span className="text-xl leading-none" aria-hidden>
          🔋
        </span>
        <h1 className="text-base font-semibold tracking-tight text-white">
          Battery Regulation Navigator
        </h1>
      </div>

      <label className="flex items-center gap-2 text-sm text-slate-300">
        Jurisdiction
        <select
          value={jurisdictionFilter}
          onChange={(event) => onJurisdictionChange(event.target.value as JurisdictionFilter)}
          className="cursor-pointer rounded-md border border-white/15 bg-white/10 px-2.5 py-1.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-white/15 focus:border-teal focus:outline-none focus:ring-2 focus:ring-teal/40"
        >
          <option value="All" className="text-slate-900">All</option>
          <option value="EU" className="text-slate-900">EU</option>
          <option value="US" className="text-slate-900">US</option>
        </select>
      </label>
    </header>
  );
}
