"use client";

import { useState, useCallback } from "react";
import Header from "@/components/Header";
import HeroSection from "@/components/HeroSection";
import CompanyInput from "@/components/CompanyInput";
import BriefingCard from "@/components/BriefingCard";
import LoadingState from "@/components/LoadingState";
import { getRandomRole, BuyerRole } from "@/lib/roles";

export default function Home() {
  const [companyName, setCompanyName] = useState("");
  const [submittedName, setSubmittedName] = useState("");
  const [rawText, setRawText] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [buyerRole, setBuyerRole] = useState<BuyerRole | null>(null);

  const handleGenerate = useCallback(async () => {
    const name = companyName.trim();
    if (!name) return;

    setError(null);
    setRawText("");
    setIsLoading(true);
    setIsStreaming(true);
    setSubmittedName(name);
    setBuyerRole(getRandomRole());

    try {
      const response = await fetch("/api/generate-briefing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ companyName: name }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(
          data.error || `Request failed with status ${response.status}`
        );
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        setRawText((prev) => prev + chunk);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "An unexpected error occurred"
      );
    } finally {
      setIsLoading(false);
      setIsStreaming(false);
    }
  }, [companyName]);

  return (
    <main className="min-h-screen bg-background">
      <Header />
      <HeroSection />
      <CompanyInput
        value={companyName}
        onChange={setCompanyName}
        onSubmit={handleGenerate}
        isLoading={isLoading}
      />

      {/* Error state */}
      {error && (
        <div className="mx-auto max-w-2xl px-6 pb-8">
          <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-4">
            <p className="text-sm text-red-400">{error}</p>
          </div>
        </div>
      )}

      {/* Loading skeleton -- only show before stream starts */}
      {isLoading && !rawText && !error && <LoadingState />}

      {/* Briefing content */}
      {(rawText || isStreaming) && (
        <BriefingCard
          rawText={rawText}
          isStreaming={isStreaming}
          companyName={submittedName}
          buyerRole={buyerRole}
        />
      )}
    </main>
  );
}
