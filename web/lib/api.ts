import type { ChunkUsed } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://battery-reg-agent-production.up.railway.app";
const REQUEST_TIMEOUT_MS = 60_000;

export const UNREACHABLE_MESSAGE = "Could not reach the server. Please check your connection and try again.";

export interface HistoryTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatStreamHandlers {
  onChunks: (chunks: ChunkUsed[]) => void;
  onToken: (token: string) => void;
}

// Parses one SSE event from /chat/stream. Returns true for the [DONE] marker.
function handleStreamEvent(event: string, handlers: ChatStreamHandlers): boolean {
  const data = event
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice("data:".length).trimStart())
    .join("\n");
  if (!data) return false;
  if (data === "[DONE]") return true;

  const payload = JSON.parse(data);
  if (Array.isArray(payload.chunks_used)) handlers.onChunks(payload.chunks_used);
  if (typeof payload.token === "string") handlers.onToken(payload.token);
  return false;
}

export async function streamChatMessage(
  message: string,
  history: HistoryTurn[],
  handlers: ChatStreamHandlers,
): Promise<void> {
  // Any failure here -- network error, timeout, a non-2xx status, an
  // unparsable event, the stream ending before [DONE] -- collapses to one
  // friendly message. The backend degrades internal errors to a fallback
  // answer inside the stream, so reaching this catch means something below
  // the API layer (the network, CORS, the server being down) failed, not
  // the agent logic. The timeout is an idle timeout, reset whenever data
  // arrives, so a long answer that keeps streaming is never cut off.
  const controller = new AbortController();
  let idleTimer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const resetIdleTimer = () => {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  };

  try {
    const res = await fetch(`${API_URL}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, conversation_history: history }),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      throw new Error(`HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) throw new Error("Stream ended before [DONE]");
      resetIdleTimer();

      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const event = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (handleStreamEvent(event, handlers)) {
          await reader.cancel();
          return;
        }
      }
    }
  } catch {
    throw new Error(UNREACHABLE_MESSAGE);
  } finally {
    clearTimeout(idleTimer);
  }
}

export interface SectionDetail {
  jurisdiction: string;
  instrument: string;
  instrument_short: string;
  section_ref: string;
  section_title: string;
  parent_context: string;
  text: string;
  url: string;
  source_type: string;
}

export async function fetchSection(instrument: string, sectionRef: string): Promise<SectionDetail> {
  const path = `/section/${encodeURIComponent(instrument)}/${encodeURIComponent(sectionRef)}`;

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  } catch {
    // A real network/timeout failure -- distinct from a resolved error
    // response below, which carries a useful, specific message.
    throw new Error(UNREACHABLE_MESSAGE);
  }

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "Could not load the full section text.");
  }

  return res.json();
}

export interface Deadline {
  topic: string;
  keywords: string[];
  jurisdiction: string;
  instrument: string;
  section_ref: string;
  deadline_date: string | null; // ISO date, e.g. "2027-02-18"; null = current law with no phase-in date
  applies_to: string;
  description: string;
  status?: "in force" | "upcoming";
  status_note?: string;
}

export async function fetchDeadlines(): Promise<Deadline[]> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/deadlines`, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  } catch {
    throw new Error(UNREACHABLE_MESSAGE);
  }
  if (!res.ok) throw new Error("Could not load deadlines.");
  return res.json();
}

export type BatteryCategory = "portable" | "lmt" | "industrial" | "ev" | "sli";

export interface ChecklistRequest {
  battery_type: BatteryCategory;
  capacity_kwh: number | null;
  chemistry: string | null;
  markets: string[]; // "EU", "US-federal"
}

export interface ChecklistItem {
  id: string;
  jurisdiction: string;
  instrument: string;
  section_ref: string;
  note: string;
  condition?: string; // e.g. "Applies only above 2 kWh (capacity not given)"
  urgency: "in_force" | "upcoming" | "undated";
  deadlines: Deadline[];
  timing_note: string | null;
}

export interface Checklist {
  battery_category: string;
  covered_markets: string[];
  no_corpus_coverage: string[];
  coverage_notes: string[];
  groups: Record<ChecklistItem["urgency"], ChecklistItem[]>;
}

export async function fetchChecklist(request: ChecklistRequest): Promise<Checklist> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/checklist`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    throw new Error(UNREACHABLE_MESSAGE);
  }
  if (!res.ok) throw new Error("Could not build the checklist.");
  return res.json();
}
