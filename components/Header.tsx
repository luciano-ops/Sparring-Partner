export default function Header() {
  return (
    <header className="border-b border-border">
      <div className="mx-auto max-w-6xl px-6 py-4 flex items-center gap-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent">
          <span className="text-sm font-bold text-white">J</span>
        </div>
        <span className="text-sm font-semibold tracking-wide text-foreground">
          Sparring Partner
        </span>
      </div>
    </header>
  );
}
