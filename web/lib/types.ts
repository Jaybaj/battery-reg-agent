export type Role = "user" | "assistant";

export interface ChunkUsed {
  section_ref: string;
  instrument: string;
  instrument_short: string;
  jurisdiction: string;
  url: string;
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  chunksUsed?: ChunkUsed[];
  isError?: boolean;
  pending?: boolean;
}

export type JurisdictionFilter = "All" | "EU" | "US";
