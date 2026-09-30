// Turns a section's stored plain text into structured lines for display.
//
// Ingested text is: a header block ("Chapter IX – …\nArticle 77 – …"), then
// paragraphs separated by blank lines. Within a paragraph, each line may start
// with a clause marker: "1." (EU numbered paragraph), "(a)", "(1)", "(i)",
// "(A)". Nesting order differs by source (EU: 1. > (a) > (i); eCFR:
// (a) > (1) > (i) > (A)), so a marker's depth is the order in which its style
// first appears within the paragraph rather than a fixed per-style level.

export interface SectionLine {
  marker: string | null;
  text: string;
  depth: number; // 0 = top level of its paragraph
  // Unmarked running text after a top-level clause ("The information shall
  // comprise:") lines up with that clause's text, not with its marker.
  alignWithClauseText: boolean;
}

type MarkerStyle = "number-dot" | "number" | "lower" | "roman" | "upper";

const MARKER = /^(\d+\.|\([0-9]+\)|\([a-z]\)|\([ivxlc]+\)|\([A-Z]\))[\s ]+/;
const ROMAN = /^\((?:i{1,3}|iv|vi{0,3}|ix|xi{0,3}|xiv|xvi{0,3}|xix|xx)\)$/;

function markerStyle(marker: string, previousLower: string | null): MarkerStyle {
  if (/^\d+\.$/.test(marker)) return "number-dot";
  if (/^\(\d+\)$/.test(marker)) return "number";
  if (/^\([A-Z]\)$/.test(marker)) return "upper";
  // "(i)", "(v)", "(x)" are letters when they continue a lettered list
  // ("(h)" then "(i)"), otherwise roman numerals.
  if (ROMAN.test(marker)) {
    const letter = marker.length === 3 ? marker[1] : null;
    const continuesLetters = letter !== null && previousLower === String.fromCharCode(letter.charCodeAt(0) - 1);
    return continuesLetters ? "lower" : "roman";
  }
  return "lower";
}

export function parseSectionText(text: string, parentContext: string): SectionLine[][] {
  const paragraphs = text
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);

  // The header block repeats what the panel's own heading already shows.
  if (paragraphs.length > 1 && parentContext && paragraphs[0].startsWith(parentContext)) {
    paragraphs.shift();
  }

  return paragraphs.map((paragraph) => {
    const styleDepths: MarkerStyle[] = [];
    let previousLower: string | null = null;

    return paragraph
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line): SectionLine => {
        const match = MARKER.exec(line);
        if (!match) {
          return { marker: null, text: line, depth: 0, alignWithClauseText: styleDepths.length > 0 };
        }
        const marker = match[1];
        const style = markerStyle(marker, previousLower);
        if (style === "lower") previousLower = marker[1];
        if (!styleDepths.includes(style)) styleDepths.push(style);
        return {
          marker,
          text: line.slice(match[0].length),
          depth: styleDepths.indexOf(style),
          alignWithClauseText: false,
        };
      });
  });
}
