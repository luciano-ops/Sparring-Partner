"""Core research agent using Claude with tool use."""

import json
import time

import anthropic

from models import (
    QueryProfile,
    ToolCall,
    ConversationTurn,
    ResearchTrace,
)
from requester_simulator import RequesterSimulator
from tools import (
    web_search,
    read_source,
    find_academic_papers,
    check_facts,
    analyze_data,
    synthesize_section,
    token_tracker,
)
import tools as _tools_module
from tracing import observe, get_tracer, wrap_client

client = wrap_client(anthropic.Anthropic())
AGENT_MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """Senior research analyst. Conduct thorough, accurate research with full source attribution.

METHOD: Search broadly, drill into authoritative sources, cross-reference claims across multiple sources. Assess credibility. Distinguish facts from opinion. Flag contradictions and knowledge gaps.

OUTPUT: Cite all claims. Include confidence levels. Final reports: Executive Summary, Findings, Methodology, Limitations, Sources. Match depth to requester expertise.

TOOLS: Max 3-4 calls per response. Prefer targeted search + read_source over many broad searches. Iterate across turns — search in one turn, read/verify in the next.

Keep responses focused and substantive. No filler."""

TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": "Search the web. Returns titles, URLs, snippets, credibility scores.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "search_type": {
                    "type": "string",
                    "enum": ["general", "academic", "news", "technical"],
                },
            },
            "required": ["query", "search_type"],
        },
    },
    {
        "name": "read_source",
        "description": "Extract structured content from a URL. Returns summary, key findings, credibility, biases.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to read"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "find_academic_papers",
        "description": "Search academic papers. Returns authors, journal, abstract, citations, conclusions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "field": {"type": "string", "description": "Academic field"},
            },
            "required": ["query", "field"],
        },
    },
    {
        "name": "check_facts",
        "description": "Fact-check a claim. Returns verification status, confidence, evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "Claim to verify"},
                "context": {"type": "string", "description": "Claim context"},
            },
            "required": ["claim", "context"],
        },
    },
    {
        "name": "analyze_data",
        "description": "Analyze a dataset. Returns findings, statistics, confidence intervals.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_description": {"type": "string", "description": "Dataset description"},
                "analysis_type": {
                    "type": "string",
                    "enum": ["trend", "comparison", "statistical", "correlation"],
                },
            },
            "required": ["dataset_description", "analysis_type"],
        },
    },
    {
        "name": "synthesize_section",
        "description": "Draft a report section from multiple sources.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Section heading"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Source summaries to synthesize",
                },
                "format": {
                    "type": "string",
                    "enum": ["executive_summary", "detailed_analysis", "bullet_points", "narrative"],
                },
            },
            "required": ["topic", "sources", "format"],
        },
    },
]


# Per-tool truncation limits (chars) for results sent back to Claude.
# Compact tools get tight limits; data-rich tools get more room.
TOOL_RESULT_LIMITS = {
    "web_search": 1500,         # 4-5 search results — titles+snippets
    "read_source": 1200,        # single doc summary + findings
    "find_academic_papers": 1500, # 3-4 papers — titles+abstracts
    "check_facts": 800,         # single verdict + evidence
    "analyze_data": 800,        # stats + findings
    "synthesize_section": 1500, # drafted text
}
DEFAULT_RESULT_LIMIT = 1200


@observe(span_type="tool")
def execute_tool(name: str, inputs: dict) -> str:
    """Execute a research tool and return serialized result."""
    if name == "web_search":
        results = web_search(inputs["query"], inputs["search_type"])
        return json.dumps([r.model_dump() for r in results])
    elif name == "read_source":
        result = read_source(inputs["url"])
        return result.model_dump_json()
    elif name == "find_academic_papers":
        results = find_academic_papers(inputs["query"], inputs["field"])
        return json.dumps([r.model_dump() for r in results])
    elif name == "check_facts":
        result = check_facts(inputs["claim"], inputs["context"])
        return result.model_dump_json()
    elif name == "analyze_data":
        result = analyze_data(
            inputs["dataset_description"], inputs["analysis_type"]
        )
        return result.model_dump_json()
    elif name == "synthesize_section":
        return synthesize_section(
            inputs["topic"], inputs["sources"], inputs["format"]
        )
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


class ResearchAgent:
    """Runs a full deep research session."""

    def __init__(self, profile: QueryProfile, verbose: bool = False):
        self.profile = profile
        self.verbose = verbose
        self.messages: list[dict] = []
        self.all_tool_calls: list[ToolCall] = []
        self.agent_tokens = 0
        self.max_conversation_turns = 6  # max requester-agent exchange pairs
        self.max_tool_rounds = 3  # max tool-use rounds per single agent turn
        self._tools_disabled_logged = False

    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    def _trim_old_context(self):
        """Trim tool results in older messages to reduce context growth.

        Keeps the last 4 messages untouched. For older user messages that
        contain tool_result blocks, truncate each result to 300 chars max.
        For older assistant messages with text blocks, truncate to 800 chars.
        """
        if len(self.messages) <= 4:
            return
        # Only trim messages before the last 4
        trim_boundary = len(self.messages) - 4
        for i in range(trim_boundary):
            msg = self.messages[i]
            content = msg.get("content")
            if content is None:
                continue
            # Trim tool_result blocks in user messages
            if msg.get("role") == "user" and isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        c = item.get("content", "")
                        if isinstance(c, str) and len(c) > 300:
                            item["content"] = c[:300] + "...[trimmed]"
            # Trim long assistant text blocks (only string content)
            elif msg.get("role") == "assistant" and isinstance(content, str):
                if len(content) > 800:
                    self.messages[i]["content"] = content[:800] + "...[trimmed]"

    @observe(span_type="function")
    def _run_agent_turn(self, user_message: str) -> tuple[str, list[ToolCall]]:
        """Run one agent turn: add user message, call Claude, handle tool loops."""
        self.messages.append({"role": "user", "content": user_message})
        turn_tool_calls = []
        tool_rounds = 0

        # If tools are degraded, don't offer them to Claude at all
        use_tools = not _tools_module.tools_degraded
        if not use_tools and not self._tools_disabled_logged:
            self._log("  [Agent] Tools disabled — responding from own knowledge")
            self._tools_disabled_logged = True

        while tool_rounds < self.max_tool_rounds:
            self._trim_old_context()
            call_kwargs = dict(
                model=AGENT_MODEL,
                max_tokens=3000,
                system=SYSTEM_PROMPT,
                messages=self.messages,
            )
            if use_tools:
                call_kwargs["tools"] = TOOL_DEFINITIONS

            response = client.messages.create(**call_kwargs)
            self.agent_tokens += response.usage.input_tokens + response.usage.output_tokens

            # Add assistant response to conversation
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                # Extract text from final response
                text_parts = []
                for block in response.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                return "\n".join(text_parts), turn_tool_calls

            # Collect tool_use blocks, hard-cap at MAX_PARALLEL_TOOLS
            MAX_PARALLEL_TOOLS = 4
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            executed = tool_use_blocks[:MAX_PARALLEL_TOOLS]
            skipped = tool_use_blocks[MAX_PARALLEL_TOOLS:]

            if skipped:
                self._log(f"  [Cap] Executing {len(executed)}/{len(tool_use_blocks)} tool calls (skipped {len(skipped)})")

            # Execute the ones we keep
            tool_results = []
            for block in executed:
                self._log(f"  [Tool] {block.name}({json.dumps(block.input)[:80]}...)")
                start = time.time()
                tokens_before = token_tracker.total

                result_str = execute_tool(block.name, block.input)
                # Truncate tool results per-tool to limit context bloat
                limit = TOOL_RESULT_LIMITS.get(block.name, DEFAULT_RESULT_LIMIT)
                result_for_claude = result_str[:limit] if len(result_str) > limit else result_str

                duration = time.time() - start
                tokens_used = token_tracker.total - tokens_before

                tc = ToolCall(
                    tool_name=block.name,
                    inputs=block.input,
                    output=result_str[:500],  # truncate for trace
                    duration=duration,
                    tokens_used=tokens_used,
                )
                turn_tool_calls.append(tc)
                self.all_tool_calls.append(tc)

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_for_claude,
                    }
                )

            # Return empty results for skipped tools so Claude doesn't hang
            for block in skipped:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": '{"note": "Tool call skipped — limit of 4 parallel calls reached. Re-request if needed."}',
                    }
                )

            if not tool_results:
                # No tool_use blocks despite stop_reason — break to avoid empty message
                break

            self.messages.append({"role": "user", "content": tool_results})
            tool_rounds += 1

        # If we hit the tool round limit, extract whatever text we have from last assistant msg
        for msg in reversed(self.messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", [])
                if isinstance(content, str):
                    return content or "I've completed my research on this topic.", turn_tool_calls
                text_parts = []
                for block in content:
                    text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
                    if text:
                        text_parts.append(text)
                if text_parts:
                    return "\n".join(text_parts), turn_tool_calls
                break
        return "I've completed my research on this topic.", turn_tool_calls

    @observe(span_type="function")
    def run_session(self) -> ResearchTrace:
        """Run a full research session and return the trace."""
        start_time = time.time()
        token_tracker.reset()
        _tools_module.tools_degraded = False
        _tools_module._haiku_consecutive_failures = 0
        turns: list[ConversationTurn] = []

        # ---- Judgment tracing metadata ----
        tracer = get_tracer()
        if tracer:
            tracer.set_session_id(self.profile.id)
            tracer.set_input(self.profile.query)
            tracer.set_attributes({
                "profile_id": self.profile.id,
                "research_type": self.profile.research_type.value,
                "domain": self.profile.domain,
                "complexity": self.profile.complexity.value,
                "requester_persona": self.profile.requester_persona.value,
                "depth_preference": self.profile.depth_preference.value,
                "time_sensitivity": self.profile.time_sensitivity.value,
            })

        self._log(f"\n{'='*60}")
        self._log(f"Research Session: {self.profile.query[:80]}")
        self._log(f"Type: {self.profile.research_type.value} | Domain: {self.profile.domain}")
        self._log(f"Persona: {self.profile.requester_persona.value} | Complexity: {self.profile.complexity.value}")
        self._log(f"{'='*60}")

        # Initialize requester
        requester = RequesterSimulator(self.profile)
        self._log(f"Behavioral arc: {requester.arc}")

        # Get initial message
        self._log(f"\n--- Turn 1: Requester ---")
        initial_msg = requester.get_initial_message()
        self._log(f"Requester: {initial_msg[:200]}...")

        turns.append(
            ConversationTurn(
                turn_number=1,
                role="requester",
                content=initial_msg,
                timestamp=time.time(),
            )
        )

        turn_num = 2
        current_requester_msg = initial_msg
        last_agent_response = ""

        while turn_num <= self.max_conversation_turns * 2 and not requester.is_done:
            # Agent turn
            self._log(f"\n--- Turn {turn_num}: Agent researching ---")
            agent_response, turn_tools = self._run_agent_turn(current_requester_msg)
            self._log(f"Agent: {agent_response[:200]}...")
            if turn_tools:
                self._log(f"  ({len(turn_tools)} tool calls)")

            turns.append(
                ConversationTurn(
                    turn_number=turn_num,
                    role="agent",
                    content=agent_response,
                    tool_calls=turn_tools,
                    timestamp=time.time(),
                )
            )
            last_agent_response = agent_response
            turn_num += 1

            if requester.is_done:
                break

            # Requester turn
            self._log(f"\n--- Turn {turn_num}: Requester ---")
            requester_msg = requester.respond(agent_response)
            self._log(f"Requester: {requester_msg[:200]}...")

            turns.append(
                ConversationTurn(
                    turn_number=turn_num,
                    role="requester",
                    content=requester_msg,
                    timestamp=time.time(),
                )
            )

            # Early exit if requester is satisfied (detected by RequesterSimulator)
            if requester.is_done:
                self._log("  [Requester satisfied — ending conversation]")
                break

            current_requester_msg = requester_msg
            turn_num += 1

        # Request final report (only if the agent hasn't already produced one)
        self._log(f"\n--- Final Report ---")
        final_prompt = (
            "Produce your final report: Executive Summary, Findings, "
            "Methodology, Limitations, Sources. Cite all sources."
        )
        try:
            final_report, final_tools = self._run_agent_turn(final_prompt)
        except Exception as e:
            self._log(f"  Final report generation failed ({e}), using last agent response")
            final_report = last_agent_response
            final_tools = []
        self._log(f"Final report length: {len(final_report)} chars")

        turns.append(
            ConversationTurn(
                turn_number=turn_num,
                role="agent",
                content=final_report,
                tool_calls=final_tools,
                timestamp=time.time(),
            )
        )

        duration = time.time() - start_time
        total_tokens = self.agent_tokens + token_tracker.total

        trace = ResearchTrace(
            profile_id=self.profile.id,
            profile=self.profile,
            turns=turns,
            tool_calls=self.all_tool_calls,
            total_tokens=total_tokens,
            duration=duration,
            final_report=final_report,
        )

        # ---- Judgment tracing output ----
        if tracer:
            tracer.set_output(final_report[:3000] if final_report else "")
            tracer.set_attributes({
                "total_turns": len(turns),
                "total_tool_calls": len(self.all_tool_calls),
                "total_tokens": total_tokens,
                "duration_seconds": round(duration, 1),
                "tools_degraded": _tools_module.tools_degraded,
            })

        self._log(f"\n{'='*60}")
        self._log(f"Session complete: {len(turns)} turns, {len(self.all_tool_calls)} tool calls")
        self._log(f"Tokens: {total_tokens:,} | Duration: {duration:.1f}s")
        self._log(f"{'='*60}\n")

        return trace
