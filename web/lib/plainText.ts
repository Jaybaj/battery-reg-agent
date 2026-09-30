import type { ChunkUsed } from "./types";

// Converts an answer's markdown to readable plain text for copying: markup is
// removed but the structure (paragraphs, list bullets, table rows) survives.
export function markdownToPlainText(markdown: string): string {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];

  for (const rawLine of lines) {
    let line = rawLine;

    if (/^\s*(-{3,}|_{3,}|\*{3,})\s*$/.test(line)) continue; // horizontal rule
    if (/^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line)) continue; // table separator row
    if (/^\s*```/.test(line)) continue; // code fence markers (keep the code itself)

    // Table rows: "| a | b |" -> "a | b"
    if (/^\s*\|.*\|\s*$/.test(line)) {
      line = line
        .trim()
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((cell) => cell.trim())
        .join(" | ");
    }

    line = line
      .replace(/^(\s*)#{1,6}\s+/, "$1") // headings
      .replace(/^(\s*)>\s?/, "$1") // blockquotes
      .replace(/^(\s*)[*+]\s+/, "$1- ") // normalise bullets to "-"
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1") // links/images -> their text
      .replace(/`([^`]*)`/g, "$1") // inline code
      .replace(/(\*\*|__)(.+?)\1/g, "$2") // bold
      .replace(/(^|[^\w*])[*_](?!\s)(.+?)(?<!\s)[*_](?=[^\w*]|$)/g, "$1$2") // italics
      .replace(/~~(.+?)~~/g, "$1"); // strikethrough

    out.push(line);
  }

  return out
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// "Sources" block for "Copy with sources": one line per distinct provision,
// with its official link (links are fine here -- this is for the user's own
// notes, unlike the answer body).
export function formatSources(chunks: ChunkUsed[]): string {
  const seen = new Set<string>();
  const lines: string[] = [];
  for (const chunk of chunks) {
    const key = `${chunk.instrument}|${chunk.section_ref}`;
    if (seen.has(key)) continue;
    seen.add(key);
    lines.push(`- ${chunk.instrument}, ${chunk.section_ref}: ${chunk.url}`);
  }
  return lines.length ? `Sources:\n${lines.join("\n")}` : "";
}
