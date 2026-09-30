"use client";

import { useEffect, useRef, useState } from "react";
import type { ChunkUsed } from "../lib/types";
import { formatSources, markdownToPlainText } from "../lib/plainText";

interface CopyActionsProps {
  content: string;
  chunks: ChunkUsed[];
}

type CopiedState = "answer" | "sources" | null;

const CONFIRMATION_MS = 2000;

async function writeToClipboard(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // navigator.clipboard is unavailable over plain http (e.g. testing on a
  // phone via the dev machine's LAN IP), so fall back to a hidden textarea.
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!copied) throw new Error("Copy failed");
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V6a2 2 0 0 1 2-2h9" strokeLinecap="round" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3.5 w-3.5" aria-hidden="true">
      <path d="m5 12.5 4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const buttonClass =
  "flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-slate-500 transition-colors " +
  "hover:bg-slate-100 hover:text-teal-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal/40";

export default function CopyActions({ content, chunks }: CopyActionsProps) {
  const [copied, setCopied] = useState<CopiedState>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  const copy = async (withSources: boolean) => {
    const answer = markdownToPlainText(content);
    const sources = withSources ? formatSources(chunks) : "";
    try {
      await writeToClipboard(sources ? `${answer}\n\n${sources}` : answer);
    } catch {
      return; // leave the buttons as they were rather than claim a copy that didn't happen
    }
    setCopied(withSources ? "sources" : "answer");
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(null), CONFIRMATION_MS);
  };

  return (
    // Always visible on touch screens (no hover there); hover/focus-revealed from md up.
    <div
      className={
        "absolute right-2 top-2 flex items-center gap-0.5 rounded-lg border border-slate-200/80 bg-white/95 " +
        "p-0.5 shadow-sm transition-opacity duration-150 md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100" +
        (copied ? " md:opacity-100" : "")
      }
    >
      <button type="button" onClick={() => copy(false)} className={buttonClass} aria-label="Copy answer" title="Copy answer">
        {copied === "answer" ? <CheckIcon /> : <CopyIcon />}
        {copied === "answer" && <span className="text-teal-dark">Copied</span>}
      </button>
      {chunks.length > 0 && (
        <button
          type="button"
          onClick={() => copy(true)}
          className={buttonClass}
          aria-label="Copy answer with sources"
          title="Copy answer with sources"
        >
          {copied === "sources" ? <CheckIcon /> : <CopyIcon />}
          {copied === "sources" ? <span className="text-teal-dark">Copied</span> : <span>+ sources</span>}
        </button>
      )}
      <span className="sr-only" aria-live="polite">
        {copied ? "Copied to clipboard" : ""}
      </span>
    </div>
  );
}
