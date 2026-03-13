export default function HeroSection() {
  return (
    <section className="mx-auto max-w-6xl px-6 pt-16 pb-8 text-center">
      <div className="relative inline-block">
        <div className="absolute -inset-x-20 -inset-y-10 bg-accent/8 blur-3xl rounded-full" />
        <h1 className="relative text-4xl font-bold tracking-tight text-foreground sm:text-5xl">
          Buyer Briefing Generator
        </h1>
      </div>
      <p className="mt-4 text-lg text-muted max-w-2xl mx-auto">
        Generate detailed buyer personas for AI sales role-play training.
        Enter a company name and get a full intelligence briefing in seconds.
      </p>
    </section>
  );
}
