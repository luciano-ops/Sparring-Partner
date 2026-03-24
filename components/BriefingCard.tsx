"use client";

import { useMemo } from "react";
import { parseBriefingSections } from "@/lib/parseStreaming";
import { BuyerRole } from "@/lib/roles";
import BriefingSection from "./BriefingSection";

interface BriefingCardProps {
  buyerText: string;
  sellerText: string;
  isBuyerStreaming: boolean;
  isSellerStreaming: boolean;
  companyName: string;
  buyerRole: BuyerRole | null;
}

export default function BriefingCard({
  buyerText,
  sellerText,
  isBuyerStreaming,
  isSellerStreaming,
  companyName,
  buyerRole,
}: BriefingCardProps) {
  const buyerSections = useMemo(
    () => parseBriefingSections(buyerText, !isBuyerStreaming),
    [buyerText, isBuyerStreaming]
  );
  const sellerSections = useMemo(
    () => parseBriefingSections(sellerText, !isSellerStreaming),
    [sellerText, isSellerStreaming]
  );

  const isStreaming = isBuyerStreaming || isSellerStreaming;
  const hasSections = buyerSections.length > 0 || sellerSections.length > 0;

  if (!hasSections && isStreaming) {
    return (
      <div className="mx-auto max-w-[1400px] px-6 pb-16">
        {buyerRole && <RoleCard role={buyerRole} companyName={companyName} />}
        <div className="flex items-center justify-center py-12">
          <div className="flex items-center gap-3 text-muted">
            <div className="flex gap-1">
              <span className="h-2 w-2 rounded-full bg-accent animate-bounce" style={{ animationDelay: "0s" }} />
              <span className="h-2 w-2 rounded-full bg-accent animate-bounce" style={{ animationDelay: "0.15s" }} />
              <span className="h-2 w-2 rounded-full bg-accent animate-bounce" style={{ animationDelay: "0.3s" }} />
            </div>
            <span className="text-sm">Claude is researching {companyName}...</span>
          </div>
        </div>
      </div>
    );
  }

  if (!hasSections) return null;

  return (
    <div className="mx-auto max-w-[1400px] px-6 pb-16">
      {buyerRole && <RoleCard role={buyerRole} companyName={companyName} />}

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* BUYER — Left side */}
        <div>
          <div className="mb-3 flex items-center gap-2">
            <span className="inline-flex items-center rounded-md bg-blue-950/50 px-2.5 py-1 text-xs font-bold uppercase tracking-wider text-blue-400 border border-blue-800/40">
              Buyer Card
            </span>
            {isBuyerStreaming && (
              <span className="inline-flex items-center gap-1.5 text-xs text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
                Streaming
              </span>
            )}
            {!isBuyerStreaming && buyerSections.length > 0 && (
              <span className="inline-flex items-center gap-1.5 text-xs text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-muted" />
                Complete
              </span>
            )}
          </div>
          <div className="space-y-4">
            {buyerSections.map((section, index) => (
              <BriefingSection key={section.number} section={section} index={index} />
            ))}
            {isBuyerStreaming && buyerSections.length === 0 && (
              <div className="rounded-lg border border-border bg-surface p-6">
                <div className="flex items-center gap-3 text-muted">
                  <div className="flex gap-1">
                    <span className="h-2 w-2 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "0s" }} />
                    <span className="h-2 w-2 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "0.15s" }} />
                    <span className="h-2 w-2 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "0.3s" }} />
                  </div>
                  <span className="text-sm">Researching company...</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* SELLER — Right side */}
        <div>
          <div className="mb-3 flex items-center gap-2">
            <span className="inline-flex items-center rounded-md bg-accent/10 px-2.5 py-1 text-xs font-bold uppercase tracking-wider text-accent border border-accent/20">
              Seller Card
            </span>
            {isSellerStreaming && (
              <span className="inline-flex items-center gap-1.5 text-xs text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
                Streaming
              </span>
            )}
            {!isSellerStreaming && sellerSections.length > 0 && (
              <span className="inline-flex items-center gap-1.5 text-xs text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-muted" />
                Complete
              </span>
            )}
          </div>
          <div className="space-y-4">
            {sellerSections.map((section, index) => (
              <BriefingSection key={section.number} section={section} index={index} />
            ))}
            {isSellerStreaming && sellerSections.length === 0 && (
              <div className="rounded-lg border border-border bg-surface p-6">
                <div className="flex items-center gap-3 text-muted">
                  <div className="flex gap-1">
                    <span className="h-2 w-2 rounded-full bg-accent animate-bounce" style={{ animationDelay: "0s" }} />
                    <span className="h-2 w-2 rounded-full bg-accent animate-bounce" style={{ animationDelay: "0.15s" }} />
                    <span className="h-2 w-2 rounded-full bg-accent animate-bounce" style={{ animationDelay: "0.3s" }} />
                  </div>
                  <span className="text-sm">Building strategy...</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function RoleCard({ role, companyName }: { role: BuyerRole; companyName: string }) {
  return (
    <div className="mb-8 animate-fade-in-up rounded-xl border-2 border-accent/30 bg-accent-light p-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-surface text-2xl shrink-0">
          {role.emoji}
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-bold uppercase tracking-widest text-accent">Your Role</span>
          </div>
          <h3 className="text-xl font-bold text-foreground">
            {role.title} <span className="font-normal text-muted">at {companyName}</span>
          </h3>
          <p className="text-sm text-muted mt-0.5">{role.description}</p>
        </div>
      </div>
      <div className="mt-4 rounded-lg bg-surface/60 p-3">
        <p className="text-xs font-medium text-muted uppercase tracking-wider mb-1">Character brief</p>
        <p className="text-sm text-foreground/80 leading-relaxed">{role.personality}</p>
      </div>
    </div>
  );
}
