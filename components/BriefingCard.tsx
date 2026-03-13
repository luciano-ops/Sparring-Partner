"use client";

import { useMemo } from "react";
import { parseBriefingSections } from "@/lib/parseStreaming";
import { BuyerRole } from "@/lib/roles";
import BriefingSection from "./BriefingSection";

interface BriefingCardProps {
  rawText: string;
  isStreaming: boolean;
  companyName: string;
  buyerRole: BuyerRole | null;
}

export default function BriefingCard({
  rawText,
  isStreaming,
  companyName,
  buyerRole,
}: BriefingCardProps) {
  const sections = useMemo(
    () => parseBriefingSections(rawText, !isStreaming),
    [rawText, isStreaming]
  );

  if (sections.length === 0 && isStreaming) {
    return (
      <div className="mx-auto max-w-6xl px-6 pb-16">
        {/* Role card shows immediately */}
        {buyerRole && <RoleCard role={buyerRole} companyName={companyName} />}
        <div className="flex items-center justify-center py-12">
          <div className="flex items-center gap-3 text-muted">
            <div className="flex gap-1">
              <span
                className="h-2 w-2 rounded-full bg-accent animate-bounce"
                style={{ animationDelay: "0s" }}
              />
              <span
                className="h-2 w-2 rounded-full bg-accent animate-bounce"
                style={{ animationDelay: "0.15s" }}
              />
              <span
                className="h-2 w-2 rounded-full bg-accent animate-bounce"
                style={{ animationDelay: "0.3s" }}
              />
            </div>
            <span className="text-sm">
              Claude is researching {companyName}...
            </span>
          </div>
        </div>
      </div>
    );
  }

  if (sections.length === 0) return null;

  return (
    <div className="mx-auto max-w-6xl px-6 pb-16">
      {/* Buyer role card */}
      {buyerRole && <RoleCard role={buyerRole} companyName={companyName} />}

      {/* Briefing header */}
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center gap-3">
        <h2 className="text-lg font-semibold text-foreground">
          Company Intel
        </h2>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center rounded-md bg-accent-light px-2.5 py-1 text-xs font-medium text-accent border border-accent/20">
            {companyName}
          </span>
          {isStreaming && (
            <span className="inline-flex items-center gap-1.5 text-xs text-muted">
              <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
              Streaming
            </span>
          )}
          {!isStreaming && (
            <span className="inline-flex items-center gap-1.5 text-xs text-muted">
              <span className="h-1.5 w-1.5 rounded-full bg-muted" />
              Complete
            </span>
          )}
        </div>
      </div>

      {/* Section grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {sections.map((section, index) => (
          <BriefingSection
            key={section.number}
            section={section}
            index={index}
          />
        ))}
      </div>
    </div>
  );
}

function RoleCard({
  role,
  companyName,
}: {
  role: BuyerRole;
  companyName: string;
}) {
  return (
    <div className="mb-8 animate-fade-in-up rounded-xl border-2 border-accent/30 bg-accent-light p-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-surface text-2xl shrink-0">
          {role.emoji}
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-bold uppercase tracking-widest text-accent">
              Your Role
            </span>
          </div>
          <h3 className="text-xl font-bold text-foreground">
            {role.title}{" "}
            <span className="font-normal text-muted">at {companyName}</span>
          </h3>
          <p className="text-sm text-muted mt-0.5">{role.description}</p>
        </div>
      </div>
      <div className="mt-4 rounded-lg bg-surface/60 p-3">
        <p className="text-xs font-medium text-muted uppercase tracking-wider mb-1">
          Character brief
        </p>
        <p className="text-sm text-foreground/80 leading-relaxed">
          {role.personality}
        </p>
      </div>
    </div>
  );
}
