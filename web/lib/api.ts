import type { ChunkUsed } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 60_000;

export const UNREACHABLE_MESSAGE = "Could not reach the server. Please check your connection and try again.";

export interface ChatApiResponse {
  answer: string;
  chunks_used: ChunkUsed[];
}

export interface HistoryTurn {
  role: "user" | "assistant";
  content: string;
}

export async function sendChatMessage(message: string, history: HistoryTurn[]): Promise<ChatApiResponse> {
  // Any failure here -- network error, timeout, a non-2xx status, an
  // unparsable body -- collapses to one friendly message. The backend itself
  // always returns 200 with valid JSON even on internal errors, so reaching
  // this catch means something below the API layer (the network, CORS, the
  // server being down) failed, not the agent logic.
  try {
    const res = await fetch(`${API_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, conversation_history: history }),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    return await res.json();
  } catch {
    throw new Error(UNREACHABLE_MESSAGE);
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
