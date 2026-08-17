"use client";

import type { ChatMessage, ChunkUsed, JurisdictionFilter } from "../lib/types";
import { matchesJurisdictionFilter } from "../lib/jurisdiction";
import AnswerMarkdown from "./AnswerMarkdown";
import CitationCard from "./CitationCard";

interface ChatMessageBubbleProps {
  message: ChatMessage;
  jurisdictionFilter: JurisdictionFilter;
  onOpenSection: (chunk: ChunkUsed) => void;
}

export default function ChatMessageBubble({ message, jurisdictionFilter, onOpenSection }: ChatMessageBubbleProps) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-br-sm bg-teal px-4 py-2.5 text-[0.925rem] leading-relaxed text-white">
          {message.content}
        </div>
      </div>
    );
  }

  if (message.pending) {
    return (
      <div className="flex justify-start">
        <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-sm border border-slate-200/80 bg-white px-4 py-3 shadow-sm">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-teal [animation-delay:-0.3s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-teal [animation-delay:-0.15s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-teal" />
        </div>
      </div>
    );
  }

  if (message.isError) {
    return (
      <div className="flex justify-start">
        <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {message.content}
        </div>
      </div>
    );
  }

  const allChunks = message.chunksUsed ?? [];
  const visibleChunks = allChunks.filter((chunk) => matchesJurisdictionFilter(chunk.jurisdiction, jurisdictionFilter));

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-slate-200/80 bg-white px-5 py-4 shadow-sm">
        <AnswerMarkdown content={message.content} />

        {allChunks.length > 0 && (
          <div className="mt-4 border-t border-slate-100 pt-3">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">Sources</p>
            {visibleChunks.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {visibleChunks.map((chunk, index) => (
                  <CitationCard key={`${chunk.instrument}-${chunk.section_ref}-${index}`} chunk={chunk} onOpen={onOpenSection} />
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-400">
                No sources for this answer match the &ldquo;{jurisdictionFilter}&rdquo; filter.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
