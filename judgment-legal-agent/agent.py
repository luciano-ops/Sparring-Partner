"""Core legal agent — agentic tool loop powered by Claude.

Uses the Judgment-wrapped Anthropic client so every API call is traced
automatically in the Judgment dashboard.
"""

from __future__ import annotations

import json
import time
from typing import Any

from instrumentation import get_wrapped_client
from models import (
    CaseProfile,
    ConversationTurn,
    ToolCall,
)
from tools import TOOL_SCHEMAS, execute_tool

AGENT_MODEL = "claude-sonnet-4-20250514"


def _build_system_prompt(profile: CaseProfile) -> str:
    docs_context = ""
    if profile.documents:
        docs_context = "\n\nAVAILABLE DOCUMENTS:\n" + "\n".join(
            f"- {d.title} ({d.doc_type}): {d.summary}" for d in profile.documents
        )

    edge_cases = ""
    if profile.edge_case_tags:
        edge_cases = (
            "\n\nSPECIAL CONSIDERATIONS: This case involves: "
            + ", ".join(profile.edge_case_tags)
            + ". Be attentive to these issues."
        )

    return f"""You are a senior legal analyst at a top-tier law firm. You provide thorough, well-researched legal counsel.

CURRENT CASE:
- Case type: {profile.case_type.value}
- Jurisdiction: {profile.jurisdiction}
- Client industry: {profile.client_industry}
- Complexity: {profile.complexity.value}
- Urgency: {profile.urgency.value}
- Opposing party: {profile.opposing_party}
{docs_context}{edge_cases}

YOUR APPROACH:
1. GATHER FACTS FIRST: Ask clarifying questions before jumping to conclusions. Understand the full picture.
2. RESEARCH BEFORE OPINING: Use search_case_law and search_statutes to find relevant precedent before giving legal opinions. Don't guess at law — look it up.
3. ANALYZE DOCUMENTS: If contracts or documents are involved, use analyze_contract_clause to identify specific risks.
4. CHECK COMPLIANCE: For regulatory matters, use check_compliance with the relevant regulations.
5. QUANTIFY RISK: Use calculate_liability when the client needs to understand financial exposure.
6. DRAFT WHEN READY: Use draft_memo only after sufficient research and analysis.

COMMUNICATION STANDARDS:
- Cite specific cases and statutes from your research (don't make them up — use tool results).
- Assess risk levels clearly: low, moderate, high, or critical.
- Provide actionable next steps, not just abstract analysis.
- Use hedging language appropriately: "based on available precedent", "in our assessment", "the strongest argument would be".
- NEVER guarantee outcomes. Legal analysis involves uncertainty.
- Know when to escalate: flag conflicts of interest, recommend outside counsel for specialized matters, note privilege issues.

CONVERSATION FLOW:
- This is turn-by-turn with the client. Be responsive to what they say.
- Don't front-load everything in one response. Build the analysis over the conversation.
- Use 1-3 tools per turn as needed. Don't overload with tool calls.
- When you've gathered enough information, provide a clear recommendation.
- In your final turn, summarize: key findings, recommended actions, risk assessment, and next steps."""


class LegalAgent:
    """Multi-turn legal agent with tool use.

    Runs an agentic loop: sends messages to Claude, executes tool calls,
    feeds results back, and continues until Claude produces a final text response.
    """

    def __init__(self, model: str = AGENT_MODEL):
        self.client = get_wrapped_client()
        self.model = model
        self.messages: list[dict] = []
        self.system_prompt: str = ""
        self.turns: list[ConversationTurn] = []
        self.tool_calls: list[ToolCall] = []
        self._turn_count = 0
        self._api_calls: list[dict] = []

    def reset(self, profile: CaseProfile):
        """Reset agent state for a new conversation."""
        self.messages = []
        self.system_prompt = _build_system_prompt(profile)
        self.turns = []
        self.tool_calls = []
        self._turn_count = 0
        self._api_calls = []

    def run_turn(self, user_message: str) -> str:
        """Send a user message and run the agent loop until a text response.

        Handles multi-step tool use internally — the agent may call
        multiple tools before producing its reply.
        """
        self.messages.append({"role": "user", "content": user_message})
        self.turns.append(ConversationTurn(role="client", content=user_message))
        self._turn_count += 1

        max_tool_rounds = 10
        tool_round = 0
        turn_tool_calls: list[ToolCall] = []

        while tool_round < max_tool_rounds:
            t0 = time.time()
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=self.system_prompt,
                tools=TOOL_SCHEMAS,
                messages=self.messages,
            )
            latency = time.time() - t0

            self._api_calls.append({
                "turn": self._turn_count,
                "tool_round": tool_round,
                "model": self.model,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "latency_s": round(latency, 3),
                "stop_reason": response.stop_reason,
            })

            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_result = execute_tool(block.name, block.input)
                        tc = ToolCall(
                            tool_name=block.name,
                            tool_input=block.input,
                            tool_result=tool_result[:2000],
                        )
                        turn_tool_calls.append(tc)
                        self.tool_calls.append(tc)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": tool_result[:1500],
                        })

                self.messages.append({"role": "user", "content": tool_results})
                tool_round += 1
            else:
                # Extract final text response
                text_parts = []
                for block in response.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
                text = "\n".join(text_parts)

                self.turns.append(
                    ConversationTurn(
                        role="agent",
                        content=text,
                        tool_calls=turn_tool_calls,
                    )
                )

                # Compress old tool results in history to save tokens.
                # The agent already digested these into its responses —
                # keeping full results just inflates future API calls.
                self._compress_old_tool_results()

                return text

        # Safety fallback
        fallback = "I need to consult with senior partners on this matter. Let me prepare a more detailed analysis and follow up with you."
        self.turns.append(ConversationTurn(role="agent", content=fallback))
        return fallback

    def _compress_old_tool_results(self):
        """Truncate tool results from previous turns to save input tokens.

        Keeps the last 2 messages intact (current turn) and compresses
        tool_result content in all older messages to a short summary.
        The agent already incorporated these results into its prior responses.
        """
        # Skip the last 2 messages (the assistant response we just got + its
        # preceding user message or tool results). Compress everything older.
        cutoff = max(0, len(self.messages) - 3)
        for msg in self.messages[:cutoff]:
            if msg["role"] == "user" and isinstance(msg["content"], list):
                for item in msg["content"]:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        content = item["content"]
                        if len(content) > 200:
                            item["content"] = content[:200] + "...[truncated]"

    def is_wrapping_up(self, response: str) -> bool:
        """Heuristic: detect if the agent is concluding the consultation."""
        wrap_signals = [
            "in summary",
            "to summarize",
            "next steps",
            "recommended course of action",
            "please don't hesitate to reach out",
            "we recommend proceeding",
            "our assessment is",
            "final recommendation",
            "LEGAL MEMORANDUM",
            "ACTION ITEMS",
        ]
        lower = response.lower()
        return any(signal in lower for signal in wrap_signals)

    def get_metadata(self) -> dict[str, Any]:
        """Return trace metadata."""
        return {
            "total_input_tokens": sum(c["input_tokens"] for c in self._api_calls),
            "total_output_tokens": sum(c["output_tokens"] for c in self._api_calls),
            "total_latency_s": round(sum(c["latency_s"] for c in self._api_calls), 3),
            "total_turns": self._turn_count,
            "total_tool_calls": len(self.tool_calls),
            "tools_used": list({tc.tool_name for tc in self.tool_calls}),
            "api_calls": self._api_calls,
        }
