import type { JurisdictionFilter } from "./types";

/** Coarse jurisdiction grouping: chunk jurisdictions like "US-CA" or "US-federal" all fall under "US". */
export function jurisdictionGroup(jurisdiction: string): "EU" | "US" | "Other" {
  if (jurisdiction === "EU" || jurisdiction.startsWith("EU-")) return "EU";
  if (jurisdiction === "US" || jurisdiction.startsWith("US-")) return "US";
  return "Other";
}

export function jurisdictionFlag(jurisdiction: string): string {
  const group = jurisdictionGroup(jurisdiction);
  if (group === "EU") return "\u{1F1EA}\u{1F1FA}"; // 🇪🇺
  if (group === "US") return "\u{1F1FA}\u{1F1F8}"; // 🇺🇸
  return "\u{1F310}"; // 🌐
}

export function matchesJurisdictionFilter(jurisdiction: string, filter: JurisdictionFilter): boolean {
  if (filter === "All") return true;
  return jurisdictionGroup(jurisdiction) === filter;
}
