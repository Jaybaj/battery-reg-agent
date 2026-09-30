"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import Header from "../../components/Header";
import SectionModal from "../../components/SectionModal";
import { fetchDeadlines, type Deadline } from "../../lib/api";
import { jurisdictionFlag, matchesJurisdictionFilter } from "../../lib/jurisdiction";
import type { ChunkUsed, JurisdictionFilter } from "../../lib/types";

const JURISDICTIONS: JurisdictionFilter[] = ["All", "EU", "US"];

const BATTERY_TYPES = ["All", "Portable", "LMT", "Industrial", "EV", "SLI"] as const;
type BatteryType = (typeof BATTERY_TYPES)[number];

// Battery categories are matched against each deadline's "applies to" text.
// Stationary energy storage systems are industrial batteries under the EU
// Battery Regulation.
const BATTERY_TYPE_PATTERNS: Record<Exclude<BatteryType, "All">, RegExp> = {
  Portable: /portable/i,
  LMT: /\bLMT\b/,
  Industrial: /industrial|stationary battery energy storage/i,
  EV: /electric vehicle/i,
  SLI: /\bSLI\b/,
};
// Deadlines that apply across the board match every battery type.
const APPLIES_TO_ALL = /^all (batteries|economic operators)/i;

function matchesBatteryType(deadline: Deadline, type: BatteryType): boolean {
  if (type === "All" || APPLIES_TO_ALL.test(deadline.applies_to)) return true;
  return BATTERY_TYPE_PATTERNS[type].test(deadline.applies_to);
}

function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function isInForce(deadline: Deadline, today: string): boolean {
  // The API computes status; fall back to the date for an older backend.
  return deadline.status ? deadline.status === "in force" : deadline.deadline_date <= today;
}

// Formatted in UTC so an ISO date never shifts a day in the viewer's timezone.
const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
function formatDate(iso: string): string {
  return DATE_FORMAT.format(new Date(`${iso}T00:00:00Z`));
}

// Curated refs are often sub-provisions ("Article 7(1)(a)", "Article 8(1),
// first subparagraph"); the section panel fetches whole articles/sections.
function baseSectionRef(sectionRef: string): string {
  return /^(Article \d+[a-z]?|§\s*[\d.]+)/.exec(sectionRef)?.[0] ?? sectionRef;
}

function FilterGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-full text-xs font-medium uppercase tracking-wide text-slate-500 sm:w-auto">{label}</span>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={label}>
        {options.map((option) => {
          const active = option === value;
          return (
            <button
              key={option}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(option)}
              className={
                "rounded-full border px-3 py-1 text-sm transition-colors " +
                (active
                  ? "border-teal bg-teal text-white"
                  : "border-slate-200 bg-white text-slate-600 hover:border-teal hover:text-teal-dark")
              }
            >
              {option}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StatusBadge({ inForce }: { inForce: boolean }) {
  return inForce ? (
    <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-600/20">
      In force
    </span>
  ) : (
    <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-700 ring-1 ring-amber-600/25">
      Upcoming
    </span>
  );
}

function TimelineItem({
  deadline,
  inForce,
  onOpenSection,
}: {
  deadline: Deadline;
  inForce: boolean;
  onOpenSection: (deadline: Deadline) => void;
}) {
  return (
    <li className="relative pl-8">
      <span
        className={
          "absolute left-0 top-1.5 h-3.5 w-3.5 rounded-full ring-4 ring-[#f9fafb] " +
          (inForce ? "bg-emerald-500" : "border-2 border-amber-500 bg-white")
        }
        aria-hidden
      />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <time dateTime={deadline.deadline_date} className="text-lg font-semibold text-navy">
          {formatDate(deadline.deadline_date)}
        </time>
        <StatusBadge inForce={inForce} />
      </div>

      <div className="mt-2 rounded-xl border border-slate-200/80 bg-white px-4 py-3 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h3 className="text-[0.95rem] font-semibold text-slate-800">{deadline.topic}</h3>
          <button
            type="button"
            onClick={() => onOpenSection(deadline)}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs shadow-sm transition-all duration-200 hover:-translate-y-px hover:border-teal hover:bg-teal-light hover:shadow-md"
            title={`Read ${baseSectionRef(deadline.section_ref)} in full`}
          >
            <span aria-hidden className="text-sm leading-none">
              {jurisdictionFlag(deadline.jurisdiction)}
            </span>
            <span className="font-medium text-slate-700">{deadline.section_ref}</span>
          </button>
        </div>
        <p className="mt-1 text-sm text-slate-500">
          <span className="font-medium text-slate-600">Applies to:</span> {deadline.applies_to}
        </p>
        <p className="mt-2 text-sm leading-relaxed text-slate-700">{deadline.description}</p>
        {inForce && deadline.status_note && (
          <p className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800">
            {deadline.status_note}
          </p>
        )}
      </div>
    </li>
  );
}

export default function DeadlinesPage() {
  const [deadlines, setDeadlines] = useState<Deadline[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jurisdiction, setJurisdiction] = useState<JurisdictionFilter>("All");
  const [batteryType, setBatteryType] = useState<BatteryType>("All");
  const [activeChunk, setActiveChunk] = useState<ChunkUsed | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchDeadlines()
      .then((data) => {
        if (!cancelled) setDeadlines(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const today = todayIso();
  const visible = useMemo(
    () =>
      (deadlines ?? [])
        .filter((d) => matchesJurisdictionFilter(d.jurisdiction, jurisdiction) && matchesBatteryType(d, batteryType))
        .sort((a, b) => a.deadline_date.localeCompare(b.deadline_date)),
    [deadlines, jurisdiction, batteryType],
  );
  const firstUpcomingIndex = visible.findIndex((d) => !isInForce(d, today));

  const openSection = (deadline: Deadline) =>
    setActiveChunk({
      section_ref: baseSectionRef(deadline.section_ref),
      instrument: deadline.instrument,
      instrument_short: deadline.instrument,
      jurisdiction: deadline.jurisdiction,
      url: "",
    });

  return (
    <div className="flex h-dvh flex-col bg-white">
      <Header />

      <main className="flex-1 overflow-y-auto bg-[#f9fafb] px-4 py-6 sm:px-6">
        <div className="mx-auto max-w-3xl">
          <h2 className="text-xl font-semibold text-navy">Compliance deadlines</h2>
          <p className="mt-1 text-sm text-slate-500">
            Verified dates from the curated deadline table, earliest first. Click a reference to read the provision.
          </p>

          <div className="mt-5 space-y-3 rounded-xl border border-slate-200/80 bg-white p-4 shadow-sm">
            <FilterGroup label="Jurisdiction" options={JURISDICTIONS} value={jurisdiction} onChange={setJurisdiction} />
            <FilterGroup label="Battery type" options={BATTERY_TYPES} value={batteryType} onChange={setBatteryType} />
          </div>

          {error && <p className="mt-6 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}

          {!deadlines && !error && (
            <div className="flex flex-col items-center gap-3 py-16 text-sm text-slate-500" role="status">
              <span className="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-teal" aria-hidden />
              Loading deadlines…
            </div>
          )}

          {deadlines && (
            <>
              <p className="mt-6 text-xs font-medium uppercase tracking-wide text-slate-400">
                {visible.length} {visible.length === 1 ? "deadline" : "deadlines"}
              </p>

              {visible.length === 0 ? (
                <p className="mt-3 text-sm text-slate-500">
                  No curated deadlines match these filters. The verified table currently covers EU Battery Regulation
                  dates only.
                </p>
              ) : (
                <ol className="relative mt-4 space-y-7 border-l-2 border-slate-200 pb-2 pl-0 [&>li]:-ml-[6px]">
                  {visible.map((deadline, index) => (
                    <Fragment key={`${deadline.section_ref}-${deadline.deadline_date}`}>
                      {index === firstUpcomingIndex && (
                        <li className="relative pl-8" aria-label="Today">
                          <span className="absolute left-0.5 top-1/2 h-2.5 w-2.5 -translate-y-1/2 rounded-full bg-teal" aria-hidden />
                          <div className="flex items-center gap-3">
                            <span className="text-xs font-semibold uppercase tracking-wide text-teal-dark">
                              Today · {formatDate(today)}
                            </span>
                            <span className="h-px flex-1 bg-teal/30" />
                          </div>
                        </li>
                      )}
                      <TimelineItem deadline={deadline} inForce={isInForce(deadline, today)} onOpenSection={openSection} />
                    </Fragment>
                  ))}
                </ol>
              )}
            </>
          )}
        </div>
      </main>

      {activeChunk && (
        <SectionModal
          key={`${activeChunk.instrument}-${activeChunk.section_ref}`}
          chunk={activeChunk}
          onClose={() => setActiveChunk(null)}
        />
      )}
    </div>
  );
}
