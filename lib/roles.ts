export interface BuyerRole {
  title: string;
  emoji: string;
  description: string;
  personality: string;
}

const BUYER_ROLES: BuyerRole[] = [
  {
    title: "CTO",
    emoji: "🏗️",
    description: "Chief Technology Officer",
    personality:
      "Strategic thinker. Cares about architecture, scalability, and long-term technical vision. Will push back on anything that adds tech debt. Budget authority but needs board buy-in for big spend.",
  },
  {
    title: "Head of AI",
    emoji: "🧠",
    description: "Head of AI / ML Engineering",
    personality:
      "Deep technical expertise. Focused on model performance, eval quality, and agent reliability. Skeptical of vendor claims — wants to see benchmarks and real results. Strong internal influence.",
  },
  {
    title: "Senior Engineer",
    emoji: "💻",
    description: "Staff / Senior ML Engineer",
    personality:
      "Hands-on builder. Cares about developer experience, integration effort, and whether the tool actually saves time. Will evaluate the SDK and docs closely. Influences the decision but doesn't own budget.",
  },
  {
    title: "Head of Product",
    emoji: "📋",
    description: "VP / Head of Product",
    personality:
      "Customer-obsessed. Cares about how AI quality impacts user experience, feature velocity, and competitive positioning. Less technical — wants business outcomes and clear ROI metrics.",
  },
];

export function getRandomRole(): BuyerRole {
  return BUYER_ROLES[Math.floor(Math.random() * BUYER_ROLES.length)];
}
