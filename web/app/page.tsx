"use client";

import { useEffect, useRef, useState } from "react";
import Header from "../components/Header";
import ChatMessageBubble from "../components/ChatMessageBubble";
import ChatInput from "../components/ChatInput";
import SectionModal from "../components/SectionModal";
import { streamChatMessage, UNREACHABLE_MESSAGE, type HistoryTurn } from "../lib/api";
import type { ChatMessage, ChunkUsed, JurisdictionFilter } from "../lib/types";

const WELCOME_MESSAGE: ChatMessage = {
  id: "welcome",
  role: "assistant",
  content:
    "Welcome to the Battery Regulation Navigator. Ask me anything about battery regulations and " +
    "battery lifecycle management — from manufacturing and transport to recycling and end-of-life " +
    "compliance, across any jurisdiction worldwide.",
};

const SUGGESTED_QUESTIONS = [
  "What do I need to sell e-bike batteries in the EU?",
  "How do I ship lithium batteries internationally?",
  "What are the EU recycled content thresholds?",
  "What regulations apply to battery recycling?",
  "When does the battery passport requirement start?",
];

// Last 5 exchanges -- keeps follow-up context without blowing the token budget.
const MAX_HISTORY_MESSAGES = 10;

// Only completed exchanges (a user question followed by a finished, non-error
// answer) go into history, so the model never sees an error bubble or a
// question whose answer is still streaming in.
function buildHistory(messages: ChatMessage[]): HistoryTurn[] {
  const history: HistoryTurn[] = [];
  for (let i = 0; i < messages.length - 1; i += 1) {
    const question = messages[i];
    const answer = messages[i + 1];
    if (
      question.role === "user" &&
      answer.role === "assistant" &&
      !answer.isError &&
      !answer.pending &&
      !answer.streaming
    ) {
      history.push({ role: "user", content: question.content }, { role: "assistant", content: answer.content });
    }
  }
  return history.slice(-MAX_HISTORY_MESSAGES);
}

let messageIdCounter = 0;
function nextMessageId(): string {
  messageIdCounter += 1;
  return `msg-${messageIdCounter}`;
}

function BatteryWatermark() {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center overflow-hidden">
      <svg
        viewBox="0 0 200 100"
        className="h-auto w-[34rem] max-w-[80%] text-teal opacity-[0.04]"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        aria-hidden="true"
      >
        <rect x="8" y="18" width="164" height="64" rx="10" />
        <rect x="176" y="34" width="14" height="32" rx="3" fill="currentColor" stroke="none" />
      </svg>
    </div>
  );
}

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [jurisdictionFilter, setJurisdictionFilter] = useState<JurisdictionFilter>("All");
  const [activeSectionChunk, setActiveSectionChunk] = useState<ChunkUsed | null>(null);
  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Each call gets its own user bubble + pending assistant bubble, appended in
  // order immediately. Multiple calls can be in flight at once -- each one's
  // stream only ever updates its own pending bubble by id, so a slower
  // earlier request can never clobber or reorder a faster later one.
  const handleSend = async (text: string) => {
    const userMessage: ChatMessage = { id: nextMessageId(), role: "user", content: text };
    const pendingId = nextMessageId();
    const pendingMessage: ChatMessage = { id: pendingId, role: "assistant", content: "", pending: true };

    const history = buildHistory(messages);

    setMessages((prev) => [...prev, userMessage, pendingMessage]);

    const updatePending = (update: (message: ChatMessage) => ChatMessage) =>
      setMessages((prev) => prev.map((message) => (message.id === pendingId ? update(message) : message)));

    let receivedText = false;
    try {
      await streamChatMessage(text, history, {
        onChunks: (chunks) => updatePending((message) => ({ ...message, chunksUsed: chunks })),
        onToken: (token) => {
          receivedText = true;
          updatePending((message) => ({
            ...message,
            content: message.content + token,
            pending: false,
            streaming: true,
          }));
        },
      });
      updatePending((message) => ({ ...message, pending: false, streaming: false }));
    } catch (error) {
      const errorText = error instanceof Error ? error.message : UNREACHABLE_MESSAGE;
      // Keep whatever already streamed in rather than replacing a partial
      // answer with an error bubble.
      updatePending((message) =>
        receivedText
          ? { ...message, content: `${message.content}\n\n_(${errorText})_`, streaming: false }
          : { id: pendingId, role: "assistant", content: errorText, isError: true },
      );
    }
  };

  const isWelcomeScreen = messages.length === 1;

  return (
    <div className="flex h-dvh flex-col bg-white">
      <Header jurisdictionFilter={jurisdictionFilter} onJurisdictionChange={setJurisdictionFilter} />

      <main
        className={
          isWelcomeScreen
            ? "relative flex-1 overflow-y-auto bg-[radial-gradient(ellipse_at_center,#f0fdfa_0%,#f9fafb_70%)] px-6 py-6"
            : "flex-1 overflow-y-auto bg-[#f9fafb] px-6 py-6"
        }
      >
        {isWelcomeScreen && <BatteryWatermark />}

        <div className="relative z-10 mx-auto flex max-w-3xl flex-col gap-4">
          {messages.map((message) => (
            <ChatMessageBubble
              key={message.id}
              message={message}
              jurisdictionFilter={jurisdictionFilter}
              onOpenSection={setActiveSectionChunk}
            />
          ))}

          {isWelcomeScreen && (
            <div className="flex flex-wrap justify-center gap-2 pt-2">
              {SUGGESTED_QUESTIONS.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => handleSend(question)}
                  className="rounded-full border border-teal px-4 py-2 text-sm text-teal transition-colors hover:bg-teal hover:text-white"
                >
                  {question}
                </button>
              ))}
            </div>
          )}

          <div ref={scrollAnchorRef} />
        </div>
      </main>

      <ChatInput onSend={handleSend} />

      {activeSectionChunk && (
        <SectionModal
          key={`${activeSectionChunk.instrument}-${activeSectionChunk.section_ref}`}
          chunk={activeSectionChunk}
          onClose={() => setActiveSectionChunk(null)}
        />
      )}
    </div>
  );
}
