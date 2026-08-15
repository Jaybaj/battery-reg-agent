"use client";

import type { JurisdictionFilter } from "../lib/types";

interface HeaderProps {
  jurisdictionFilter: JurisdictionFilter;
  onJurisdictionChange: (value: JurisdictionFilter) => void;
}

export default function Header({ jurisdictionFilter, onJurisdictionChange }: HeaderProps) {
  return (
    <header className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white/80 px-6 py-4 backdrop-blur-sm">
      <div className="flex items-center gap-2.5">
        <span className="text-xl leading-none">🔋</span>
        <h1 className="text-base font-semibold tracking-tight text-slate-900">
          Battery Regulation Navigator
        </h1>
      </div>

      <label className="flex items-center gap-2 text-sm text-slate-500">
        Jurisdiction
        <select
          value={jurisdictionFilter}
          onChange={(event) => onJurisdictionChange(event.target.value as JurisdictionFilter)}
          className="cursor-pointer rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:border-slate-400 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
        >
          <option value="All">All</option>
          <option value="EU">EU</option>
          <option value="US">US</option>
        </select>
      </label>
    </header>
  );
}
