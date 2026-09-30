"use client";

import { useRef, useState, type FormEvent } from "react";
import Header from "../../components/Header";
import ChatMessageBubble from "../../components/ChatMessageBubble";
import SectionModal from "../../components/SectionModal";
import StatusBadge, { type DeadlineStatus } from "../../components/StatusBadge";
import {
  fetchChecklist,
  streamChatMessage,
  UNREACHABLE_MESSAGE,
  type BatteryCategory,
  type Checklist,
  type ChecklistItem,
} from "../../lib/api";
import { formatIsoDate } from "../../lib/format";
import { jurisdictionFlag } from "../../lib/jurisdiction";
import type { ChatMessage, ChunkUsed } from "../../lib/types";

const BATTERY_TYPES: { value: BatteryCategory; label: string; phrase: string }[] = [
  { value: "portable", label: "Portable", phrase: "portable" },
  { value: "lmt", label: "LMT (light means of transport)", phrase: "LMT" },
  { value: "industrial", label: "Industrial", phrase: "industrial" },
  { value: "ev", label: "EV (electric vehicle)", phrase: "EV" },
  { value: "sli", label: "SLI (starting, lighting, ignition)", phrase: "SLI" },
];

const CHEMISTRIES = ["Li-ion", "Lead-acid", "NiMH", "Other"] as const;
type Chemistry = (typeof CHEMISTRIES)[number];

const ROLES = ["Manufacturer", "Importer", "Distributor", "Recycler"] as const;
type Role = (typeof ROLES)[number];

const MARKETS = [
  { value: "EU", label: "EU", phrase: "the EU" },
  { value: "US-federal", label: "US Federal", phrase: "the US (federal)" },
] as const;
type Market = (typeof MARKETS)[number]["value"];

const GROUPS: { key: ChecklistItem["urgency"]; title: string; subtitle: string }[] = [
  { key: "in_force", title: "In force now", subtitle: "Already applies. Confirm you comply today." },
  { key: "upcoming", title: "Upcoming", subtitle: "Soonest first. Start preparing now." },
  { key: "undated", title: "Timing to confirm", subtitle: "Applies, but the verified deadline table has no date for it." },
];

const URGENCY_STATUS: Record<ChecklistItem["urgency"], DeadlineStatus> = {
  in_force: "in force",
  upcoming: "upcoming",
  undated: "undated",
};

interface FormState {
  batteryType: BatteryCategory;
  capacity: string;
  chemistry: Chemistry;
  markets: Market[];
  role: Role;
}

function buildQuestion(form: FormState): string {
  const type = BATTERY_TYPES.find((t) => t.value === form.batteryType)!.phrase;
  const chemistry = form.chemistry === "Other" ? "" : `${form.chemistry} `;
  const capacity = form.capacity.trim() ? ` of ${form.capacity.trim()} kWh` : "";
  const markets = MARKETS.filter((m) => form.markets.includes(m.value))
    .map((m) => m.phrase)
    .join(" and ");
  const article = /^[AEIOU]/.test(form.role) ? "an" : "a";
  return (
    `I am ${article} ${form.role.toLowerCase()} placing ${chemistry}${type} batteries${capacity} on the market in ` +
    `${markets}. What are all my obligations, in order of urgency?`
  );
}

const fieldClass =
  "w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition-[border-color,background-color,box-shadow] duration-200 " +
  "focus:border-teal focus:bg-white focus:shadow-[0_0_0_3px_rgba(13,148,136,0.12)] focus:outline-none";

function Field({ label, htmlFor, hint, children }: { label: string; htmlFor?: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

function ChecklistCard({
  item,
  done,
  onToggle,
  onOpenSection,
}: {
  item: ChecklistItem;
  done: boolean;
  onToggle: () => void;
  onOpenSection: (item: ChecklistItem) => void;
}) {
  const checkboxId = `check-${item.id}`;
  return (
    <li
      className={
        "rounded-xl border bg-white px-4 py-3 shadow-sm transition-colors " +
        (done ? "border-slate-200/60 bg-slate-50/80" : "border-slate-200/80")
      }
    >
      <div className="flex items-start gap-3">
        <input
          id={checkboxId}
          type="checkbox"
          checked={done}
          onChange={onToggle}
          className="mt-1 h-4 w-4 shrink-0 cursor-pointer rounded border-slate-300 accent-teal"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <label
              htmlFor={checkboxId}
              className={
                "cursor-pointer text-[0.95rem] font-semibold " +
                (done ? "text-slate-400 line-through decoration-slate-300" : "text-slate-800")
              }
            >
              {item.note}
            </label>
            <StatusBadge status={URGENCY_STATUS[item.urgency]} />
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => onOpenSection(item)}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs shadow-sm transition-all duration-200 hover:-translate-y-px hover:border-teal hover:bg-teal-light hover:shadow-md"
              title={`Read ${item.section_ref} in full`}
            >
              <span aria-hidden className="text-sm leading-none">
                {jurisdictionFlag(item.jurisdiction)}
              </span>
              <span className="font-medium text-slate-700">{item.section_ref}</span>
              <span className="text-slate-400">· {item.instrument}</span>
            </button>
            {item.condition && (
              <span className="rounded-md bg-amber-50 px-2 py-0.5 text-xs text-amber-800">{item.condition}</span>
            )}
          </div>

          {item.deadlines.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm">
              {item.deadlines.map((deadline) => (
                <li key={`${deadline.section_ref}-${deadline.deadline_date}`} className="text-slate-600">
                  <span className="font-medium text-navy">
                    {deadline.deadline_date ? formatIsoDate(deadline.deadline_date) : "Current law, no phase-in date"}
                  </span>
                  <span className="text-slate-400"> · {deadline.section_ref} · </span>
                  {deadline.status === "in force" ? "in force" : "upcoming"}
                  {deadline.status === "in force" && deadline.status_note && (
                    <p className="mt-1 rounded-md bg-amber-50 px-2 py-1 text-xs leading-relaxed text-amber-800">
                      {deadline.status_note}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
          {item.timing_note && <p className="mt-2 text-xs text-slate-500">{item.timing_note}</p>}
        </div>
      </div>
    </li>
  );
}

export default function CheckerPage() {
  const [form, setForm] = useState<FormState>({
    batteryType: "lmt",
    capacity: "",
    chemistry: "Li-ion",
    markets: ["EU"],
    role: "Manufacturer",
  });
  const [submittedRole, setSubmittedRole] = useState<Role | null>(null);
  const [checklist, setChecklist] = useState<Checklist | null>(null);
  const [checklistLoading, setChecklistLoading] = useState(false);
  const [checklistError, setChecklistError] = useState<string | null>(null);
  const [guidance, setGuidance] = useState<ChatMessage | null>(null);
  const [done, setDone] = useState<Set<string>>(new Set());
  const [activeChunk, setActiveChunk] = useState<ChunkUsed | null>(null);
  // Ignore results from an earlier submission that finish after a newer one.
  const runRef = useRef(0);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((prev) => ({ ...prev, [key]: value }));
  const toggleMarket = (market: Market) =>
    update("markets", form.markets.includes(market) ? form.markets.filter((m) => m !== market) : [...form.markets, market]);

  const capacityValue = form.capacity.trim() === "" ? null : Number(form.capacity);
  const capacityInvalid = capacityValue !== null && (!Number.isFinite(capacityValue) || capacityValue < 0);
  const canSubmit = form.markets.length > 0 && !capacityInvalid;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    const run = ++runRef.current;
    const isCurrent = () => run === runRef.current;

    setSubmittedRole(form.role);
    setDone(new Set());
    setChecklist(null);
    setChecklistError(null);
    setChecklistLoading(true);
    const guidanceId = `guidance-${run}`;
    setGuidance({ id: guidanceId, role: "assistant", content: "", pending: true });

    // The checklist comes from the verified tables; the guidance from the agent. Both start together.
    fetchChecklist({
      battery_type: form.batteryType,
      capacity_kwh: capacityValue,
      chemistry: form.chemistry === "Other" ? null : form.chemistry,
      markets: form.markets,
    })
      .then((data) => isCurrent() && setChecklist(data))
      .catch((err: Error) => isCurrent() && setChecklistError(err.message))
      .finally(() => isCurrent() && setChecklistLoading(false));

    const updateGuidance = (change: (message: ChatMessage) => ChatMessage) =>
      isCurrent() && setGuidance((prev) => (prev && prev.id === guidanceId ? change(prev) : prev));
    let receivedText = false;
    try {
      await streamChatMessage(buildQuestion(form), [], {
        onChunks: (chunks) => updateGuidance((m) => ({ ...m, chunksUsed: chunks })),
        onToken: (token) => {
          receivedText = true;
          updateGuidance((m) => ({ ...m, content: m.content + token, pending: false, streaming: true }));
        },
      });
      updateGuidance((m) => ({ ...m, pending: false, streaming: false }));
    } catch (error) {
      const errorText = error instanceof Error ? error.message : UNREACHABLE_MESSAGE;
      updateGuidance((m) =>
        receivedText
          ? { ...m, content: `${m.content}\n\n_(${errorText})_`, streaming: false }
          : { id: guidanceId, role: "assistant", content: errorText, isError: true },
      );
    }
  };

  const toggleDone = (id: string) =>
    setDone((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const openSection = (item: ChecklistItem) =>
    setActiveChunk({
      section_ref: item.section_ref,
      instrument: item.instrument,
      instrument_short: item.instrument,
      jurisdiction: item.jurisdiction,
      url: "",
    });

  const totalItems = checklist ? Object.values(checklist.groups).reduce((sum, items) => sum + items.length, 0) : 0;

  return (
    <div className="flex h-dvh flex-col bg-white">
      <Header />

      <main className="flex-1 overflow-y-auto bg-[#f9fafb] px-4 py-6 sm:px-6">
        <div className="mx-auto max-w-3xl">
          <h2 className="text-xl font-semibold text-navy">Compliance checker</h2>
          <p className="mt-1 text-sm text-slate-500">
            Describe your battery and where you&rsquo;re selling it to get a checklist of obligations, most urgent first.
          </p>

          <form
            onSubmit={handleSubmit}
            className="mt-5 grid gap-4 rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm sm:grid-cols-2"
          >
            <Field label="Battery type" htmlFor="battery-type">
              <select
                id="battery-type"
                value={form.batteryType}
                onChange={(e) => update("batteryType", e.target.value as BatteryCategory)}
                className={fieldClass}
              >
                {BATTERY_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Capacity (kWh)" htmlFor="capacity" hint="Optional. Some EU obligations only apply above 2 kWh.">
              <input
                id="capacity"
                type="number"
                inputMode="decimal"
                min="0"
                step="any"
                placeholder="e.g. 0.5"
                value={form.capacity}
                onChange={(e) => update("capacity", e.target.value)}
                aria-invalid={capacityInvalid}
                className={fieldClass + (capacityInvalid ? " border-red-300" : "")}
              />
            </Field>

            <Field label="Chemistry" htmlFor="chemistry">
              <select
                id="chemistry"
                value={form.chemistry}
                onChange={(e) => update("chemistry", e.target.value as Chemistry)}
                className={fieldClass}
              >
                {CHEMISTRIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </Field>

            <Field label="Your role" htmlFor="role">
              <select id="role" value={form.role} onChange={(e) => update("role", e.target.value as Role)} className={fieldClass}>
                {ROLES.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </Field>

            <fieldset className="sm:col-span-2">
              <legend className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">Target markets</legend>
              <div className="flex flex-wrap gap-2">
                {MARKETS.map((market) => {
                  const checked = form.markets.includes(market.value);
                  return (
                    <label
                      key={market.value}
                      className={
                        "flex cursor-pointer items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm transition-colors " +
                        (checked ? "border-teal bg-teal-light text-teal-dark" : "border-slate-200 bg-white text-slate-600 hover:border-teal")
                      }
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleMarket(market.value)}
                        className="h-3.5 w-3.5 accent-teal"
                      />
                      {market.label}
                    </label>
                  );
                })}
                <span className="flex items-center gap-2 rounded-full border border-dashed border-slate-200 px-3.5 py-1.5 text-sm text-slate-400">
                  US state EPR laws (coming soon)
                </span>
              </div>
              {form.markets.length === 0 && <p className="mt-1.5 text-xs text-red-600">Select at least one market.</p>}
            </fieldset>

            <div className="sm:col-span-2">
              <button
                type="submit"
                disabled={!canSubmit}
                className="rounded-full bg-linear-to-br from-teal to-teal-dark px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-[filter,box-shadow] duration-200 hover:shadow-md hover:brightness-95 disabled:cursor-not-allowed disabled:from-slate-300 disabled:to-slate-300 disabled:shadow-none"
              >
                Check my obligations
              </button>
            </div>
          </form>

          {checklistLoading && (
            <div className="flex flex-col items-center gap-3 py-12 text-sm text-slate-500" role="status">
              <span className="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-teal" aria-hidden />
              Building your checklist…
            </div>
          )}
          {checklistError && <p className="mt-6 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{checklistError}</p>}

          {checklist && (
            <section className="mt-8" aria-label="Obligations checklist">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-lg font-semibold text-navy">Your obligations</h3>
                <span className="text-sm text-slate-500">
                  {done.size} of {totalItems} done
                </span>
              </div>
              <p className="mt-1 text-sm text-slate-500">
                {checklist.battery_category}. These obligations attach to the battery itself; which fall on you as{" "}
                {submittedRole && /^[AEIOU]/.test(submittedRole) ? "an" : "a"} {submittedRole?.toLowerCase()} is covered
                in the guidance below.
              </p>

              {[...checklist.coverage_notes, ...checklist.no_corpus_coverage.map((m) => `${m} is not in the verified corpus yet.`)].map(
                (note) => (
                  <p key={note} className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800">
                    {note}
                  </p>
                ),
              )}

              {totalItems === 0 && (
                <p className="mt-4 text-sm text-slate-500">No obligations in the verified tables match this battery.</p>
              )}

              {GROUPS.map(({ key, title, subtitle }) =>
                checklist.groups[key].length > 0 ? (
                  <div key={key} className="mt-6">
                    <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
                      {title} <span className="font-normal text-slate-400">({checklist.groups[key].length})</span>
                    </h4>
                    <p className="text-xs text-slate-400">{subtitle}</p>
                    <ul className="mt-3 space-y-3">
                      {checklist.groups[key].map((item) => (
                        <ChecklistCard
                          key={item.id}
                          item={item}
                          done={done.has(item.id)}
                          onToggle={() => toggleDone(item.id)}
                          onOpenSection={openSection}
                        />
                      ))}
                    </ul>
                  </div>
                ) : null,
              )}
            </section>
          )}

          {guidance && (
            <section className="mt-10" aria-label="Guidance">
              <h3 className="mb-3 text-lg font-semibold text-navy">Guidance for your situation</h3>
              <ChatMessageBubble message={guidance} jurisdictionFilter="All" onOpenSection={setActiveChunk} />
            </section>
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
