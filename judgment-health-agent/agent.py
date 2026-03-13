"""Core health agent — agentic tool loop powered by Claude."""

from __future__ import annotations

import json
import time
import anthropic
from pathlib import Path
from models import Trace, ConversationTurn, ToolCall, AgentMode
from tools import TOOL_DEFINITIONS, execute_tool
from instrumentation import get_wrapped_client

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text()


class HealthAgent:
    """Multi-turn health agent with tool use.

    Runs an agentic loop: sends messages to Claude, executes tool calls,
    feeds results back, and continues until Claude produces a final text response.
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.client = get_wrapped_client()
        self.model = model
        self.messages: list[dict] = []
        self.trace = Trace(profile_id="", mode=AgentMode.TRIAGE)
        self._turn_count = 0

    def reset(self, profile_id: str, mode: AgentMode):
        """Reset agent state for a new conversation."""
        self.messages = []
        self.trace = Trace(profile_id=profile_id, mode=mode)
        self._turn_count = 0

    def run_turn(self, user_message: str) -> str:
        """Send a user message and run the agent loop until a text response.

        Handles multi-step tool use internally — the agent may call
        multiple tools before producing its reply.
        """
        self.messages.append({"role": "user", "content": user_message})
        self.trace.turns.append(ConversationTurn(role="user", content=user_message))
        self._turn_count += 1

        max_tool_rounds = 10  # Safety limit on tool call loops (10 tools available)
        tool_round = 0

        while tool_round < max_tool_rounds:
            t0 = time.time()
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=self.messages,
            )
            latency = time.time() - t0

            # Record metadata
            self.trace.metadata.setdefault("api_calls", []).append({
                "turn": self._turn_count,
                "tool_round": tool_round,
                "model": self.model,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "latency_s": round(latency, 3),
                "stop_reason": response.stop_reason,
            })

            # Add full assistant response to messages
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                # Process tool calls
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = execute_tool(block.name, block.input)
                        self.trace.tool_calls.append(ToolCall(
                            tool=block.name,
                            input=block.input,
                            output=result,
                        ))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })

                self.messages.append({"role": "user", "content": tool_results})
                tool_round += 1
            else:
                # Extract final text response
                text_parts = []
                for block in response.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
                text = "".join(text_parts)

                self.trace.turns.append(ConversationTurn(role="assistant", content=text))
                return text

        # Safety fallback if tool loop exceeded
        fallback = "I apologize, but I'm having difficulty processing your request. Please consult a healthcare provider directly."
        self.trace.turns.append(ConversationTurn(role="assistant", content=fallback))
        return fallback

    def is_wrapping_up(self, response: str) -> bool:
        """Heuristic: detect if the agent is concluding the conversation."""
        wrap_signals = [
            "take care",
            "don't hesitate to reach out",
            "wishing you",
            "hope this helps",
            "feel free to come back",
            "PATIENT INTAKE SUMMARY",
            "recommended action:",
            "urgency level:",
            "in summary",
            "to summarize",
        ]
        lower = response.lower()
        return any(signal in lower for signal in wrap_signals)

    def get_trace(self) -> Trace:
        """Return the conversation trace for evaluation."""
        # Calculate totals
        calls = self.trace.metadata.get("api_calls", [])
        self.trace.metadata["total_input_tokens"] = sum(c["input_tokens"] for c in calls)
        self.trace.metadata["total_output_tokens"] = sum(c["output_tokens"] for c in calls)
        self.trace.metadata["total_latency_s"] = round(sum(c["latency_s"] for c in calls), 3)
        self.trace.metadata["total_turns"] = self._turn_count
        self.trace.metadata["total_tool_calls"] = len(self.trace.tool_calls)
        self.trace.metadata["tools_used"] = list({tc.tool for tc in self.trace.tool_calls})
        return self.trace
