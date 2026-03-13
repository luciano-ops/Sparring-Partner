"use client";

import { BriefingSection as BriefingSectionType } from "@/lib/types";

interface BriefingSectionProps {
  section: BriefingSectionType;
  index: number;
}

function renderContent(text: string): string {
  let html = text
    // Bold text
    .replace(/\*\*(.+?)\*\*/g, '<strong class="text-foreground font-semibold">$1</strong>')
    // [ESTIMATED] and [ESTIMATED ...] badges (with optional description)
    .replace(
      /\[ESTIMATED(?:\s+[^\]]+)?\]/g,
      '<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-900/30 text-amber-400 border border-amber-800/50 ml-1 align-middle">EST.</span>'
    )
    // Convert lines starting with - or numbered lists into list items
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();
      if (trimmed.startsWith("- ")) {
        return `<li class="flex gap-2 text-sm leading-relaxed text-muted"><span class="text-accent mt-1.5 shrink-0">&bull;</span><span>${trimmed.slice(2)}</span></li>`;
      }
      if (/^\d+\.\s/.test(trimmed)) {
        const content = trimmed.replace(/^\d+\.\s/, "");
        return `<li class="flex gap-2 text-sm leading-relaxed text-muted"><span class="text-accent mt-1.5 shrink-0">&bull;</span><span>${content}</span></li>`;
      }
      if (trimmed === "" || trimmed === "##") return '<div class="h-2"></div>';
      return `<p class="text-sm leading-relaxed text-muted">${trimmed}</p>`;
    })
    .join("");

  // Wrap consecutive <li> elements in <ul>
  html = html.replace(
    /(<li[^>]*>.*?<\/li>)+/g,
    '<ul class="space-y-1.5">$&</ul>'
  );

  return html;
}

export default function BriefingSection({
  section,
  index,
}: BriefingSectionProps) {
  return (
    <div
      className="animate-fade-in-up rounded-lg border border-border bg-surface p-6 transition-colors hover:bg-surface-elevated"
      style={{ animationDelay: `${index * 0.05}s` }}
    >
      {/* Section header */}
      <div className="mb-3 flex items-baseline gap-2">
        <span className="font-mono text-xs font-bold tracking-widest text-accent">
          {section.number}
        </span>
        <span className="text-xs text-border">/</span>
        <span className="text-xs font-semibold uppercase tracking-wider text-muted">
          {section.title}
        </span>
      </div>

      {/* Divider */}
      <div className="mb-4 h-px bg-border" />

      {/* Content */}
      <div
        className="space-y-1"
        dangerouslySetInnerHTML={{ __html: renderContent(section.content) }}
      />

      {/* Streaming cursor */}
      {!section.isComplete && (
        <span className="inline-block h-4 w-1.5 bg-accent animate-blink ml-0.5 mt-1 rounded-sm" />
      )}
    </div>
  );
}
