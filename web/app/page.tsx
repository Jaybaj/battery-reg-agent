"use client";

import { useEffect, useRef, useState } from "react";
import Header from "../components/Header";
import ChatMessageBubble from "../components/ChatMessageBubble";
import ChatInput from "../components/ChatInput";
import SectionModal from "../components/SectionModal";
import { sendChatMessage, UNREACHABLE_MESSAGE } from "../lib/api";
import type { ChatMessage, ChunkUsed, JurisdictionFilter } from "../lib/types";

const WELCOME_MESSAGE: ChatMessage = {
  id: "welcome",
  role: "assistant",
  content:
    "Welcome to the Battery Regulation Navigator. Ask me anything about battery regulations and " +
    "battery lifecycle management — from manufacturing and transport to recycling and end-of-life " +
    "compliance, across any jurisdiction worldwide.",
};

let messageIdCounter = 0;
function nextMessageId(): string {
  messageIdCounter += 1;
  return `msg-${messageIdCounter}`;
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
  // completion only ever updates its own pending bubble by id, so a slower
  // earlier request can never clobber or reorder a faster later one.
  const handleSend = async (text: string) => {
    const userMessage: ChatMessage = { id: nextMessageId(), role: "user", content: text };
    const pendingId = nextMessageId();
    const pendingMessage: ChatMessage = { id: pendingId, role: "assistant", content: "", pending: true };

    const history = messages
      .filter((message) => message.id !== "welcome" && !message.pending)
      .map((message) => ({ role: message.role, content: message.content }));

    setMessages((prev) => [...prev, userMessage, pendingMessage]);

    try {
      const response = await sendChatMessage(text, history);
      setMessages((prev) =>
        prev.map((message) =>
          message.id === pendingId
            ? { id: pendingId, role: "assistant", content: response.answer, chunksUsed: response.chunks_used }
            : message,
        ),
      );
    } catch (error) {
      setMessages((prev) =>
        prev.map((message) =>
          message.id === pendingId
            ? {
                id: pendingId,
                role: "assistant",
                content: error instanceof Error ? error.message : UNREACHABLE_MESSAGE,
                isError: true,
              }
            : message,
        ),
      );
    }
  };

  return (
    <div className="flex h-dvh flex-col bg-slate-50">
      <Header jurisdictionFilter={jurisdictionFilter} onJurisdictionChange={setJurisdictionFilter} />

      <main className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          {messages.map((message) => (
            <ChatMessageBubble
              key={message.id}
              message={message}
              jurisdictionFilter={jurisdictionFilter}
              onOpenSection={setActiveSectionChunk}
            />
          ))}

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
