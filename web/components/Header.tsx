"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { JurisdictionFilter } from "../lib/types";

interface HeaderProps {
  // The chat page's source filter; pages without one omit both props.
  jurisdictionFilter?: JurisdictionFilter;
  onJurisdictionChange?: (value: JurisdictionFilter) => void;
}

// shortLabel is shown on phones, where three full labels don't fit beside the logo.
const NAV_LINKS = [
  { href: "/", label: "Chat", shortLabel: "Chat" },
  { href: "/deadlines", label: "Deadlines", shortLabel: "Deadlines" },
  { href: "/checker", label: "Compliance Checker", shortLabel: "Checker" },
];

export default function Header({ jurisdictionFilter, onJurisdictionChange }: HeaderProps) {
  const pathname = usePathname();

  return (
    <header className="flex shrink-0 items-center justify-between gap-4 bg-navy px-6 py-4">
      <div className="flex min-w-0 items-center gap-5">
        <Link href="/" className="flex items-center gap-2.5">
          <svg
            viewBox="0 0 24 24"
            className="h-5 w-5 shrink-0 text-teal"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <rect x="2" y="7" width="17" height="10" rx="2" />
            <path d="M22 11v2" />
            <path d="M6 10v4M9.5 10v4" />
          </svg>
          <h1 className="hidden text-base font-semibold tracking-tight text-white sm:block">
            Battery Regulation Navigator
          </h1>
        </Link>

        <nav className="flex items-center gap-1" aria-label="Main">
          {NAV_LINKS.map(({ href, label, shortLabel }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={
                  "rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors " +
                  (active ? "bg-white/10 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white")
                }
              >
                <span className="sm:hidden">{shortLabel}</span>
                <span className="hidden sm:inline">{label}</span>
              </Link>
            );
          })}
        </nav>
      </div>

      {jurisdictionFilter && onJurisdictionChange && (
        <label className="flex shrink-0 items-center gap-2 text-sm text-slate-300">
          <span className="hidden sm:inline">Jurisdiction</span>
          <select
            value={jurisdictionFilter}
            onChange={(event) => onJurisdictionChange(event.target.value as JurisdictionFilter)}
            aria-label="Jurisdiction"
            className="cursor-pointer rounded-md border border-white/15 bg-white/10 px-2.5 py-1.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-white/15 focus:border-teal focus:outline-none focus:ring-2 focus:ring-teal/40"
          >
            <option value="All" className="text-slate-900">All</option>
            <option value="EU" className="text-slate-900">EU</option>
            <option value="US" className="text-slate-900">US</option>
          </select>
        </label>
      )}
    </header>
  );
}
