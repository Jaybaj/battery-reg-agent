import type { Metadata } from "next";

// The page itself is a client component, so its metadata lives here.
export const metadata: Metadata = {
  title: "Deadlines · Battery Regulation Navigator",
  description: "Verified battery regulation compliance deadlines, in force and upcoming.",
};

export default function DeadlinesLayout({ children }: { children: React.ReactNode }) {
  return children;
}
