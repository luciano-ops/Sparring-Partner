import Anthropic from "@anthropic-ai/sdk";
import { BUYER_PROMPT, SELLER_PROMPT } from "@/lib/prompts";

const client = new Anthropic();

export async function POST(request: Request) {
  try {
    const { companyName, side } = await request.json();

    if (!companyName || typeof companyName !== "string") {
      return Response.json(
        { error: "Company name is required" },
        { status: 400 }
      );
    }

    const isBuyer = side === "buyer";
    const systemPrompt = isBuyer ? BUYER_PROMPT : SELLER_PROMPT;
    const userMessage = isBuyer
      ? `Research and generate a Buyer Card for: ${companyName.trim()}`
      : `Research and generate a Seller Card for: ${companyName.trim()}`;

    const response = await client.messages.create({
      model: "claude-opus-4-6",
      max_tokens: 16000,
      stream: true,
      system: systemPrompt,
      tools: [
        {
          type: "web_search_20250305",
          name: "web_search",
          max_uses: 10,
        },
      ],
      messages: [
        {
          role: "user",
          content: `${userMessage}\n\nSearch the web for current information about this company — their product, funding, team, AI/agent usage, tech stack, and recent news. Use real data to make the briefing as accurate and specific as possible.`,
        },
      ],
    });

    const encoder = new TextEncoder();

    const readableStream = new ReadableStream({
      async start(controller) {
        try {
          for await (const event of response) {
            if (event.type === "content_block_delta") {
              if (event.delta.type === "text_delta") {
                controller.enqueue(encoder.encode(event.delta.text));
              }
            }
          }
          controller.close();
        } catch (err) {
          console.error("Stream error:", err);
          controller.enqueue(
            encoder.encode("\n\n[Error: Stream interrupted. Please try again.]")
          );
          controller.close();
        }
      },
    });

    return new Response(readableStream, {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-cache",
      },
    });
  } catch (error: unknown) {
    console.error("API route error:", error);

    const isAuthError =
      error instanceof Anthropic.AuthenticationError ||
      (error instanceof Anthropic.APIError && error.status === 401);

    if (isAuthError) {
      return Response.json(
        {
          error:
            "Invalid API key. Set ANTHROPIC_API_KEY in your .env.local file.",
        },
        { status: 401 }
      );
    }

    const message =
      error instanceof Error ? error.message : "Failed to generate briefing";
    return Response.json({ error: message }, { status: 500 });
  }
}
