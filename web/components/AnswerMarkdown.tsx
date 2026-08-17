import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

function iconForHeading(text: string): string {
  const lower = text.toLowerCase();
  if (lower.includes("situational")) return "\u{1F9ED}"; // compass
  if (lower.includes("applicable regulation")) return "\u{1F4DA}"; // books
  if (lower.includes("step") || lower.includes("guidance")) return "✅"; // check
  if (lower.includes("deadline") || lower.includes("timeline")) return "⏱️"; // stopwatch
  if (lower.includes("caveat")) return "⚠️"; // warning
  if (lower.includes("disclaimer")) return "ℹ️"; // info
  return "▸"; // small triangle bullet
}

const components: Components = {
  h2: ({ children }) => {
    const text = String(children);
    return (
      <div className="mt-5 border-l-2 border-teal py-0.5 pl-3 first:mt-0">
        <h2 className="flex items-center gap-2 text-[0.95rem] font-semibold text-slate-800">
          <span aria-hidden className="text-sm">
            {iconForHeading(text)}
          </span>
          {children}
        </h2>
      </div>
    );
  },
  h3: ({ children }) => <h3 className="mt-3 text-sm font-semibold text-slate-800">{children}</h3>,
  p: ({ children }) => <p className="mt-2 text-[0.925rem] leading-relaxed text-slate-700">{children}</p>,
  ul: ({ children }) => <ul className="mt-2 list-disc space-y-1 pl-5 text-[0.925rem] text-slate-700">{children}</ul>,
  ol: ({ children, start }) => (
    <ol start={start} className="mt-2 list-decimal space-y-1 pl-5 text-[0.925rem] text-slate-700">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-teal underline decoration-teal/40 underline-offset-2 hover:text-teal-dark"
    >
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em] text-slate-800">{children}</code>
  ),
};

export default function AnswerMarkdown({ content }: { content: string }) {
  return (
    <div className="[&>*:first-child]:mt-0">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
