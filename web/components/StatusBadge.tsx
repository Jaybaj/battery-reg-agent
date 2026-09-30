export type DeadlineStatus = "in force" | "upcoming" | "undated";

const STYLES: Record<DeadlineStatus, { label: string; className: string }> = {
  "in force": { label: "In force", className: "bg-emerald-50 text-emerald-700 ring-emerald-600/20" },
  upcoming: { label: "Upcoming", className: "bg-amber-50 text-amber-700 ring-amber-600/25" },
  undated: { label: "Date to confirm", className: "bg-slate-100 text-slate-600 ring-slate-400/25" },
};

export default function StatusBadge({ status }: { status: DeadlineStatus }) {
  const { label, className } = STYLES[status];
  return (
    <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${className}`}>{label}</span>
  );
}
