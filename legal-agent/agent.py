"""Core legal research agent using Claude with tool use."""

import json
import time

import anthropic

from models import (
    QueryProfile,
    ToolCall,
    ConversationTurn,
    LegalResearchTrace,
)
from requester_simulator import RequesterSimulator
from tools import (
    search_case_law,
    read_statute,
    find_legal_precedents,
    check_jurisdiction,
    analyze_contract_clause,
    draft_legal_section,
    token_tracker,
)
import tools as _tools_module
from tracing import observe, get_tracer, wrap_client


client = wrap_client(anthropic.Anthropic())
AGENT_MODEL = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Complexity × Depth → (max_conversation_turns, max_tool_rounds)
# Drives realistic trace-length variety: simple lookups finish fast,
# expert-level exhaustive research runs deep.
# ---------------------------------------------------------------------------
SESSION_SHAPE = {
    # Simple
    ("Simple", "Overview"):    (2, 2),
    ("Simple", "Detailed"):    (3, 2),
    ("Simple", "Exhaustive"):  (4, 3),
    # Moderate
    ("Moderate", "Overview"):  (3, 2),
    ("Moderate", "Detailed"):  (5, 3),
    ("Moderate", "Exhaustive"): (6, 3),
    # Complex
    ("Complex", "Overview"):   (4, 3),
    ("Complex", "Detailed"):   (6, 3),
    ("Complex", "Exhaustive"): (7, 4),
    # Expert_Level
    ("Expert_Level", "Overview"):   (5, 3),
    ("Expert_Level", "Detailed"):   (7, 4),
    ("Expert_Level", "Exhaustive"): (8, 4),
}
_DEFAULT_SHAPE = (6, 3)  # fallback — matches previous hardcoded behaviour

SYSTEM_PROMPT = """Senior legal research analyst. Conduct thorough, accurate legal research with full source attribution and proper citation format.

METHOD: Search case law broadly, analyze applicable statutes, cross-reference legal precedents across jurisdictions. Assess the strength of authorities. Distinguish binding from persuasive precedent. Flag circuit splits, unsettled law, and potential counterarguments.

SOURCE INTEGRITY:
- Always reference and build on what your tools return. When a tool provides case holdings, statute text, or analysis, incorporate those findings directly into your response.
- Do not invent case names, citation numbers, or statute references beyond what tools return. If you need more information, call another tool rather than guessing.
- When tool results conflict, flag the discrepancy and explain both positions.
- For each major conclusion, note your confidence level (HIGH/MODERATE/LOW) based on how well-supported it is by your research findings.

OUTPUT: Cite all cases (Party v. Party, Reporter Citation (Year)) and statutes (Title, Section) as returned by tools — do not modify citations. Final reports: Executive Summary, Legal Analysis, Applicable Precedents, Risk Assessment, Recommendations, Sources. Match depth to requester expertise.

TOOLS: Max 3-4 calls per response. Use a variety of tools — don't rely only on search_case_law. A good research turn typically combines different tool types:
- search_case_law or find_legal_precedents for case authority
- read_statute for statutory text
- check_jurisdiction when multiple jurisdictions are involved
- analyze_contract_clause when contract language is at issue
- draft_legal_section to synthesize after gathering sources

Avoid redundant searches — if you already have results on a topic, build on them rather than re-searching with similar queries.

Keep responses focused and substantive. Use proper legal writing conventions. No filler."""

# Research-type-specific behavioral overrides.
# These are appended to SYSTEM_PROMPT to make each interaction type distinct.
RESEARCH_TYPE_PROMPTS = {
    "Contract_Review": (
        "\n\nINTERACTION MODE: DOCUMENT REVIEW\n"
        "MANDATORY: You MUST call analyze_contract_clause at least twice in this session. "
        "This is a document review — your job is to examine specific contract language.\n"
        "- Your FIRST tool call each turn should be analyze_contract_clause\n"
        "- Focus on clause-level risks, ambiguities, enforceability, and missing protections\n"
        "- Provide redline suggestions and alternative language\n"
        "- Do NOT just search case law and give general advice — analyze the actual document"
    ),
    "Regulatory_Assessment": (
        "\n\nINTERACTION MODE: COMPLIANCE CHECK\n"
        "MANDATORY: You MUST call check_compliance at least twice in this session. "
        "This is a compliance assessment — your job is to check regulatory requirements.\n"
        "- Your FIRST tool call each turn should be check_compliance or read_statute\n"
        "- Structure output as a compliance checklist: requirement → status → gap → remediation\n"
        "- Focus on which regulations apply, whether the client is compliant, and penalties for gaps\n"
        "- Do NOT just search case law and give general advice — assess compliance status"
    ),
    "Case_Law_Research": (
        "\n\nINTERACTION MODE: RESEARCH REQUEST\n"
        "MANDATORY: You MUST call search_case_law or find_legal_precedents at least 3 times per turn. "
        "This is a pure research request — your job is to find and present case law.\n"
        "- Present findings as 'the research shows...' not 'I advise you to...'\n"
        "- Map the evolution of doctrine, note circuit splits, flag open questions\n"
        "- Do NOT give strategic advice — deliver research findings and let the requester draw conclusions"
    ),
    "Due_Diligence": (
        "\n\nINTERACTION MODE: RISK ASSESSMENT\n"
        "MANDATORY: You MUST call calculate_liability at least once AND check_jurisdiction at least once. "
        "This is a risk assessment — your job is to quantify and categorize legal risks.\n"
        "- Build a risk matrix: risk → likelihood → impact → severity (HIGH/MEDIUM/LOW)\n"
        "- Quantify financial exposure where possible using calculate_liability\n"
        "- Flag deal-breakers vs manageable risks\n"
        "- Do NOT just search case law and give general advice — assess and quantify risks"
    ),
    "Statutory_Analysis": (
        "\n\nINTERACTION MODE: COMPLIANCE CHECK\n"
        "MANDATORY: You MUST call read_statute at least 3 times in this session. "
        "This is a statutory analysis — your job is to read and interpret specific statutes.\n"
        "- Your FIRST tool call each turn should be read_statute\n"
        "- Map obligations, thresholds, safe harbors, and penalties from the statute text\n"
        "- Compare requirements across jurisdictions when relevant\n"
        "- Do NOT just search case law — focus on reading and interpreting the actual statutes"
    ),
    "Legal_Memorandum": (
        "\n\nINTERACTION MODE: LEGAL CONSULTATION\n"
        "You are preparing a formal legal memorandum with balanced analysis.\n"
        "- Use all available tools broadly\n"
        "- Formal memo structure: Issue, Rule, Application, Conclusion\n"
        "- Predict likely outcomes and recommend strategy"
    ),
}

TOOL_DEFINITIONS = [
    {
        "name": "search_case_law",
        "description": "Search case law databases for relevant cases. Returns case names, citations, holdings, and relevance assessment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Legal search query (e.g., 'breach of fiduciary duty corporate director')"},
                "jurisdiction": {
                    "type": "string",
                    "description": "Jurisdiction to search (e.g., 'Federal', 'California', 'New York', 'Delaware')",
                },
            },
            "required": ["query", "jurisdiction"],
        },
    },
    {
        "name": "read_statute",
        "description": "Read and extract content from a specific statute or regulation. Returns structured summary and applicability notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "statute_reference": {"type": "string", "description": "Statute reference (e.g., 'UCC Article 2', '15 U.S.C. 1', 'Cal. Civ. Code 1542')"},
                "jurisdiction": {"type": "string", "description": "Jurisdiction of the statute"},
            },
            "required": ["statute_reference", "jurisdiction"],
        },
    },
    {
        "name": "find_legal_precedents",
        "description": "Find relevant legal precedents for a specific legal issue. Returns cases with their legal principles and subsequent treatment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "legal_issue": {"type": "string", "description": "The specific legal issue (e.g., 'enforceability of non-compete agreements')"},
                "area_of_law": {"type": "string", "description": "Area of law (e.g., 'employment law', 'contract law', 'securities regulation')"},
            },
            "required": ["legal_issue", "area_of_law"],
        },
    },
    {
        "name": "check_jurisdiction",
        "description": "Verify jurisdictional applicability for a legal matter. Returns governing law, conflicts analysis, and forum considerations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue": {"type": "string", "description": "The legal issue to check jurisdiction for"},
                "jurisdictions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of potentially applicable jurisdictions",
                },
            },
            "required": ["issue", "jurisdictions"],
        },
    },
    {
        "name": "analyze_contract_clause",
        "description": "Analyze a specific contract clause for risks, enforceability, and recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "clause_text": {"type": "string", "description": "The contract clause text to analyze"},
                "analysis_type": {
                    "type": "string",
                    "enum": ["risk_assessment", "enforceability", "compliance", "negotiation_leverage"],
                    "description": "Type of analysis to perform",
                },
            },
            "required": ["clause_text", "analysis_type"],
        },
    },
    {
        "name": "draft_legal_section",
        "description": "Draft a section of a legal memo or brief from multiple sources.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Section heading or topic"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Source summaries (case holdings, statute excerpts) to synthesize",
                },
                "format": {
                    "type": "string",
                    "enum": ["executive_summary", "legal_analysis", "risk_assessment", "recommendations"],
                    "description": "Format of the section to draft",
                },
            },
            "required": ["topic", "sources", "format"],
        },
    },
]

# Per-tool truncation limits (chars) for results sent back to Claude.
TOOL_RESULT_LIMITS = {
    "search_case_law": 1500,
    "read_statute": 1200,
    "find_legal_precedents": 1500,
    "check_jurisdiction": 800,
    "analyze_contract_clause": 800,
    "draft_legal_section": 1500,
}
DEFAULT_RESULT_LIMIT = 1200


@observe(span_type="tool")
def execute_tool(name: str, inputs: dict) -> str:
    """Execute a legal research tool and return serialized result."""
    if name == "search_case_law":
        results = search_case_law(inputs["query"], inputs["jurisdiction"])
        return json.dumps([r.model_dump() for r in results])
    elif name == "read_statute":
        result = read_statute(inputs["statute_reference"], inputs["jurisdiction"])
        return result.model_dump_json()
    elif name == "find_legal_precedents":
        results = find_legal_precedents(inputs["legal_issue"], inputs["area_of_law"])
        return json.dumps([r.model_dump() for r in results])
    elif name == "check_jurisdiction":
        result = check_jurisdiction(inputs["issue"], inputs["jurisdictions"])
        return result.model_dump_json()
    elif name == "analyze_contract_clause":
        result = analyze_contract_clause(inputs["clause_text"], inputs["analysis_type"])
        return result.model_dump_json()
    elif name == "draft_legal_section":
        return draft_legal_section(inputs["topic"], inputs["sources"], inputs["format"])
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


class LegalResearchAgent:
    """Runs a full legal research session."""

    def __init__(self, profile: QueryProfile, verbose: bool = False):
        self.profile = profile
        self.verbose = verbose
        self.messages: list[dict] = []
        self.all_tool_calls: list[ToolCall] = []
        self.agent_tokens = 0

        shape_key = (profile.complexity.value, profile.depth_preference.value)
        turns, tools = SESSION_SHAPE.get(shape_key, _DEFAULT_SHAPE)
        self.max_conversation_turns = turns
        self.max_tool_rounds = tools
        self._tools_disabled_logged = False

        # Build research-type-specific system prompt
        rt_key = profile.research_type.value
        self._system_prompt = SYSTEM_PROMPT + RESEARCH_TYPE_PROMPTS.get(rt_key, "")

    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    def _trim_old_context(self):
        """Trim tool results in older messages to reduce context growth."""
        if len(self.messages) <= 6:
            return
        trim_boundary = len(self.messages) - 6
        for i in range(trim_boundary):
            msg = self.messages[i]
            content = msg.get("content")
            if content is None:
                continue
            if msg.get("role") == "user" and isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        c = item.get("content", "")
                        if isinstance(c, str) and len(c) > 500:
                            item["content"] = c[:500] + "...[trimmed]"
            elif msg.get("role") == "assistant" and isinstance(content, str):
                if len(content) > 1000:
                    self.messages[i]["content"] = content[:1000] + "...[trimmed]"

    @observe(span_type="function")
    def _run_agent_turn(self, user_message: str) -> tuple[str, list[ToolCall]]:
        """Run one agent turn: add user message, call Claude, handle tool loops."""
        self.messages.append({"role": "user", "content": user_message})

        turn_tool_calls = []
        tool_rounds = 0

        use_tools = not _tools_module.tools_degraded
        if not use_tools and not self._tools_disabled_logged:
            self._log("  [Agent] Tools disabled -- responding from own knowledge")
            self._tools_disabled_logged = True

        while tool_rounds < self.max_tool_rounds:
            self._trim_old_context()

            call_kwargs = dict(
                model=AGENT_MODEL,
                max_tokens=3000,
                system=self._system_prompt,
                messages=self.messages,
            )
            if use_tools:
                call_kwargs["tools"] = TOOL_DEFINITIONS

            response = client.messages.create(**call_kwargs)
            self.agent_tokens += response.usage.input_tokens + response.usage.output_tokens
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                text_parts = []
                for block in response.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                return "\n".join(text_parts), turn_tool_calls

            MAX_PARALLEL_TOOLS = 4
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            executed = tool_use_blocks[:MAX_PARALLEL_TOOLS]
            skipped = tool_use_blocks[MAX_PARALLEL_TOOLS:]

            if skipped:
                self._log(f"  [Cap] Executing {len(executed)}/{len(tool_use_blocks)} tool calls (skipped {len(skipped)})")

            tool_results = []
            for block in executed:
                self._log(f"  [Tool] {block.name}({json.dumps(block.input)[:80]}...)")
                start = time.time()
                tokens_before = token_tracker.total
                result_str = execute_tool(block.name, block.input)

                limit = TOOL_RESULT_LIMITS.get(block.name, DEFAULT_RESULT_LIMIT)
                result_for_claude = result_str[:limit] if len(result_str) > limit else result_str

                duration = time.time() - start
                tokens_used = token_tracker.total - tokens_before

                tc = ToolCall(
                    tool_name=block.name,
                    inputs=block.input,
                    output=result_str[:500],
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

            for block in skipped:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": '{"note": "Tool call skipped -- limit of 4 parallel calls reached. Re-request if needed."}',
                    }
                )

            if not tool_results:
                break

            self.messages.append({"role": "user", "content": tool_results})
            tool_rounds += 1

        # Extract text from last assistant message
        for msg in reversed(self.messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", [])
                if isinstance(content, str):
                    return content or "I've completed my legal research on this matter.", turn_tool_calls
                text_parts = []
                for block in content:
                    text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
                    if text:
                        text_parts.append(text)
                if text_parts:
                    return "\n".join(text_parts), turn_tool_calls
                break

        return "I've completed my legal research on this matter.", turn_tool_calls

    @observe(span_type="function")
    def run_session(self) -> LegalResearchTrace:
        """Run a full legal research session and return the trace."""
        start_time = time.time()
        token_tracker.reset()
        _tools_module.tools_degraded = False
        _tools_module._haiku_consecutive_failures = 0

        turns: list[ConversationTurn] = []

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
        self._log(f"Legal Research Session: {self.profile.query[:80]}")
        self._log(f"Type: {self.profile.research_type.value} | Domain: {self.profile.domain}")
        self._log(f"Persona: {self.profile.requester_persona.value} | Complexity: {self.profile.complexity.value}")
        self._log(f"{'='*60}")

        requester = RequesterSimulator(self.profile, max_turns=self.max_conversation_turns)
        self._log(f"Behavioral arc: {requester.arc} | Shape: {self.max_conversation_turns} turns, {self.max_tool_rounds} tool rounds")

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

            if requester.is_done:
                self._log("  [Requester satisfied -- ending conversation]")
                break

            current_requester_msg = requester_msg
            turn_num += 1

        self._log(f"\n--- Final Report ---")
        final_prompt = (
            "Produce your final legal memorandum: Executive Summary, Legal Analysis, "
            "Applicable Precedents, Risk Assessment, Recommendations, Sources. "
            "Cite only cases and statutes that were returned by your research tools — do not "
            "add any citations from memory. For each major conclusion, include your confidence "
            "level (HIGH/MODERATE/LOW). If any area has limited or conflicting sources, say so."
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

        trace = LegalResearchTrace(
            profile_id=self.profile.id,
            profile=self.profile,
            turns=turns,
            tool_calls=self.all_tool_calls,
            total_tokens=total_tokens,
            duration=duration,
            final_report=final_report,
        )

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
