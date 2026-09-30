import type { Metadata } from "next";

// The page itself is a client component, so its metadata lives here.
export const metadata: Metadata = {
  title: "Compliance Checker · Battery Regulation Navigator",
  description: "Check which battery regulations apply to your product, most urgent first.",
};

export default function CheckerLayout({ children }: { children: React.ReactNode }) {
  return children;
}
