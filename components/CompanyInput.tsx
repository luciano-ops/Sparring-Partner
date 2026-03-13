"use client";

interface CompanyInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  isLoading: boolean;
}

export default function CompanyInput({
  value,
  onChange,
  onSubmit,
  isLoading,
}: CompanyInputProps) {
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !isLoading && value.trim()) {
      onSubmit();
    }
  };

  return (
    <div className="mx-auto max-w-2xl px-6 pb-12">
      <div className="flex flex-col sm:flex-row gap-3">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Enter a company name..."
          disabled={isLoading}
          className="flex-1 rounded-lg border border-border bg-surface px-4 py-3 text-foreground placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50 disabled:opacity-50 transition-all"
        />
        <button
          onClick={onSubmit}
          disabled={isLoading || !value.trim()}
          className="rounded-lg bg-accent px-6 py-3 text-sm font-semibold text-white transition-all hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 min-w-[160px]"
        >
          {isLoading ? (
            <>
              <svg
                className="h-4 w-4 animate-spin"
                viewBox="0 0 24 24"
                fill="none"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              Generating...
            </>
          ) : (
            "Generate Briefing"
          )}
        </button>
      </div>
    </div>
  );
}
