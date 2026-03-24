"""Core health research agent using Claude with tool use."""

import json
import time

import anthropic

from models import (
    QueryProfile,
    ToolCall,
    ConversationTurn,
    HealthResearchTrace,
)
from requester_simulator import RequesterSimulator
from tools import (
    search_medical_literature,
    read_clinical_study,
    find_treatment_guidelines,
    check_drug_interactions,
    analyze_clinical_data,
    draft_clinical_section,
    token_tracker,
)
import tools as _tools_module
from tracing import observe, get_tracer, wrap_client

client = wrap_client(anthropic.Anthropic())
AGENT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """Senior health/medical research analyst. Conduct thorough, evidence-based clinical research with full source attribution and rigorous methodology assessment.

METHOD: Search medical literature broadly (PubMed, Cochrane, WHO), drill into high-quality clinical studies, cross-reference findings across systematic reviews and RCTs. Assess study quality using GRADE criteria. Check treatment guidelines from major medical bodies. Verify drug interactions and contraindications. Distinguish Level I evidence from expert opinion.

SOURCE GROUNDING (CRITICAL):
- ONLY cite sources, studies, statistics, and URLs that were explicitly returned by your tool calls.
- NEVER fabricate citations, invent study names, or generate URLs not present in tool results.
- NEVER add statistics, sample sizes, effect sizes, or p-values beyond what your tools returned.
- If your tools returned insufficient evidence on a sub-topic, explicitly state "insufficient evidence retrieved" rather than filling gaps from general knowledge.
- When synthesizing across tool results, attribute each claim to the specific tool result it came from.

CONFIDENCE LEVELS — tag every major claim:
- HIGH: Directly supported by tool results from systematic reviews, meta-analyses, or multiple concordant RCTs.
- MODERATE: Supported by a single RCT or cohort study from tool results, or guideline recommendation with moderate evidence level.
- LOW: Based on limited tool results (case studies, expert opinion, single observational study), or extrapolated from related evidence.
- INSUFFICIENT: Tool results did not return direct evidence on this point. State this explicitly.

OUTPUT: Cite all claims with study references from tool results only. Include confidence levels and evidence grades. Final reports: Clinical Summary, Key Findings with Evidence Levels, Treatment Considerations, Drug Interactions/Safety, Limitations & Evidence Gaps, Sources. Match depth to requester expertise (physician vs student vs patient advocate).

TOOL SELECTION (CRITICAL — follow strictly):
- Max 3-4 tool calls per response. Max 8-12 total tool calls per session.
- NEVER repeat a tool call with the same name AND similar inputs. If you already searched for a topic, do NOT search again with slightly rephrased query.
- search_medical_literature: Max 3-4 searches per session. Each search should target a DISTINCT sub-topic. Do NOT run multiple overlapping searches.
- read_clinical_study: Only read the 2-3 highest-credibility studies from search results. Do NOT read every result — prioritize systematic reviews and meta-analyses (credibility >0.8).
- check_drug_interactions: USE THIS when the query involves drug comparisons, polypharmacy, or treatment safety. Do not skip it in favor of more literature searches.
- analyze_clinical_data: USE THIS when the query asks about outcomes, effectiveness comparisons, or epidemiological patterns. Do not substitute with extra literature searches.
- find_treatment_guidelines: Call ONCE per session for the primary condition. Do not call multiple times for the same condition.
- draft_clinical_section: Use only in the final turn to synthesize. Do not call multiple times.

TOOL SELECTION DECISION TREE:
1. First turn: 1-2 targeted searches + 1 guideline lookup (if clinical question)
2. Second turn: Read 2-3 best studies from results + specialized tool (drug interactions OR clinical data analysis) if relevant
3. Final turn: Synthesize — do NOT call more search tools. Use draft_clinical_section if needed.

STOP CONDITION: If you have evidence from 3+ high-quality sources covering the main question, STOP searching. More searches ≠ better research.

Keep responses focused and clinically substantive. No filler."""

TOOL_DEFINITIONS = [
    {
        "name": "search_medical_literature",
        "description": "Search medical databases (PubMed, Cochrane, WHO). Returns titles, URLs, snippets, credibility scores.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Medical search query"},
                "search_type": {
                    "type": "string",
                    "enum": ["clinical_trial", "systematic_review", "meta_analysis", "guidelines", "epidemiological"],
                },
            },
            "required": ["query", "search_type"],
        },
    },
    {
        "name": "read_clinical_study",
        "description": "Extract structured content from a clinical study URL. Returns study type, findings, limitations, credibility.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL of the clinical study to read"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "find_treatment_guidelines",
        "description": "Find clinical practice guidelines from major medical bodies (AHA, WHO, NICE, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "condition": {"type": "string", "description": "Medical condition or disease"},
                "specialty": {"type": "string", "description": "Medical specialty area"},
            },
            "required": ["condition", "specialty"],
        },
    },
    {
        "name": "check_drug_interactions",
        "description": "Check for drug-drug interactions and contraindications.",
        "input_schema": {
            "type": "object",
            "properties": {
                "drug_a": {"type": "string", "description": "First drug name"},
                "drug_b": {"type": "string", "description": "Second drug name"},
            },
            "required": ["drug_a", "drug_b"],
        },
    },
    {
        "name": "analyze_clinical_data",
        "description": "Analyze clinical or epidemiological datasets. Returns findings, statistics, confidence intervals.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_description": {"type": "string", "description": "Description of the clinical dataset"},
                "analysis_type": {
                    "type": "string",
                    "enum": ["survival", "comparative_effectiveness", "epidemiological", "dose_response"],
                },
            },
            "required": ["dataset_description", "analysis_type"],
        },
    },
    {
        "name": "draft_clinical_section",
        "description": "Draft a section of a clinical report from multiple sources.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Section heading/topic"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Source summaries to synthesize",
                },
                "format": {
                    "type": "string",
                    "enum": ["clinical_summary", "evidence_review", "risk_benefit_analysis", "treatment_protocol"],
                },
            },
            "required": ["topic", "sources", "format"],
        },
    },
]


# Per-tool truncation limits (chars) for results sent back to Claude.
TOOL_RESULT_LIMITS = {
    "search_medical_literature": 2000,
    "read_clinical_study": 1800,
    "find_treatment_guidelines": 2000,
    "check_drug_interactions": 1200,
    "analyze_clinical_data": 1200,
    "draft_clinical_section": 2000,
}
DEFAULT_RESULT_LIMIT = 1800


@observe(span_type="tool")
def execute_tool(name: str, inputs: dict) -> str:
    """Execute a health research tool and return serialized result."""
    if name == "search_medical_literature":
        results = search_medical_literature(inputs["query"], inputs["search_type"])
        return json.dumps([r.model_dump() for r in results])
    elif name == "read_clinical_study":
        result = read_clinical_study(inputs["url"])
        return result.model_dump_json()
    elif name == "find_treatment_guidelines":
        results = find_treatment_guidelines(inputs["condition"], inputs["specialty"])
        return json.dumps([r.model_dump() for r in results])
    elif name == "check_drug_interactions":
        result = check_drug_interactions(inputs["drug_a"], inputs["drug_b"])
        return result.model_dump_json()
    elif name == "analyze_clinical_data":
        result = analyze_clinical_data(
            inputs["dataset_description"], inputs["analysis_type"]
        )
        return result.model_dump_json()
    elif name == "draft_clinical_section":
        return draft_clinical_section(
            inputs["topic"], inputs["sources"], inputs["format"]
        )
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


class HealthResearchAgent:
    """Runs a full health research session."""

    def __init__(self, profile: QueryProfile, verbose: bool = False,
                 max_conversation_turns: int = 6, max_tool_rounds: int = 3,
                 forced_behavior: str | None = None):
        self.profile = profile
        self.verbose = verbose
        self.forced_behavior = forced_behavior
        self.messages: list[dict] = []
        self.all_tool_calls: list[ToolCall] = []
        self.agent_tokens = 0
        self.max_conversation_turns = max_conversation_turns
        self.max_tool_rounds = max_tool_rounds
        self._tools_disabled_logged = False

    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    def _trim_old_context(self):
        """Trim tool results in older messages to reduce context growth.

        Preserves more content than aggressive trimming to prevent the agent
        from losing source details (URLs, study names, statistics) needed
        for grounded final reports.
        """
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
                        if isinstance(c, str) and len(c) > 800:
                            item["content"] = c[:800] + "...[trimmed]"
            elif msg.get("role") == "assistant" and isinstance(content, str):
                if len(content) > 1500:
                    self.messages[i]["content"] = content[:1500] + "...[trimmed]"

    @observe(span_type="function")
    def _run_agent_turn(self, user_message: str) -> tuple[str, list[ToolCall]]:
        """Run one agent turn: add user message, call Claude, handle tool loops."""
        self.messages.append({"role": "user", "content": user_message})
        turn_tool_calls = []
        tool_rounds = 0

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

            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                text_parts = []
                for block in response.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                return "\n".join(text_parts), turn_tool_calls

            MAX_PARALLEL_TOOLS = 3
            MAX_SESSION_TOOLS = 12
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            # Enforce session-level tool budget
            remaining_budget = MAX_SESSION_TOOLS - len(self.all_tool_calls)
            if remaining_budget <= 0:
                self._log(f"  [Cap] Session tool budget ({MAX_SESSION_TOOLS}) exhausted — skipping all tool calls")
                # Still need to send tool_result for each block
                budget_skipped = tool_use_blocks
                tool_use_blocks = []
            else:
                budget_skipped = []

            # Deduplicate: skip tool calls with same name+inputs as previous calls
            deduped = []
            deduped_out = []  # blocks removed by dedup — still need tool_result responses
            for block in tool_use_blocks:
                key = (block.name, json.dumps(block.input, sort_keys=True))
                if any(
                    (tc.tool_name == block.name and json.dumps(tc.inputs, sort_keys=True) == key[1])
                    for tc in self.all_tool_calls
                ):
                    self._log(f"  [Dedup] Skipping duplicate: {block.name}({json.dumps(block.input)[:60]})")
                    deduped_out.append(block)
                    continue
                deduped.append(block)
            tool_use_blocks = deduped

            cap = min(MAX_PARALLEL_TOOLS, remaining_budget)
            executed = tool_use_blocks[:cap]
            skipped = tool_use_blocks[cap:] + deduped_out + budget_skipped

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
                        "content": '{"note": "Tool call skipped — limit of 4 parallel calls reached. Re-request if needed."}',
                    }
                )

            if not tool_results:
                break

            self.messages.append({"role": "user", "content": tool_results})
            tool_rounds += 1

        for msg in reversed(self.messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", [])
                if isinstance(content, str):
                    return content or "I've completed my clinical research on this topic.", turn_tool_calls
                text_parts = []
                for block in content:
                    text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
                    if text:
                        text_parts.append(text)
                if text_parts:
                    return "\n".join(text_parts), turn_tool_calls
                break
        return "I've completed my clinical research on this topic.", turn_tool_calls

    @observe(span_type="function")
    def run_session(self) -> HealthResearchTrace:
        """Run a full health research session and return the trace."""
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
        self._log(f"Health Research Session: {self.profile.query[:80]}")
        self._log(f"Type: {self.profile.research_type.value} | Domain: {self.profile.domain}")
        self._log(f"Persona: {self.profile.requester_persona.value} | Complexity: {self.profile.complexity.value}")
        self._log(f"{'='*60}")

        requester = RequesterSimulator(self.profile, max_turns=self.max_conversation_turns,
                                       forced_behavior=self.forced_behavior)
        self._log(f"Behavioral arc: {requester.arc}"
                  f"{f' (forced: {self.forced_behavior})' if self.forced_behavior else ''}")

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
                self._log("  [Requester satisfied — ending conversation]")
                break

            current_requester_msg = requester_msg
            turn_num += 1

        self._log(f"\n--- Final Report ---")
        final_prompt = (
            "Produce your final clinical report based EXCLUSIVELY on evidence retrieved "
            "from your tool calls during this session. Do NOT add any citations, studies, "
            "statistics, or URLs that were not returned by your tools.\n\n"
            "Structure: Clinical Summary, Key Findings with Evidence Levels, Treatment "
            "Considerations, Drug Interactions/Safety, Limitations & Evidence Gaps, Sources.\n\n"
            "Requirements:\n"
            "- Tag every key finding with a confidence level: HIGH, MODERATE, LOW, or INSUFFICIENT.\n"
            "- In the Sources section, list ONLY sources that appeared in your tool results.\n"
            "- In Limitations & Evidence Gaps, explicitly note any sub-topics where your tools "
            "returned no direct evidence.\n"
            "- Do not fill evidence gaps with general knowledge — state the gap instead."
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

        trace = HealthResearchTrace(
            profile_id=self.profile.id,
            profile=self.profile,
            turns=turns,
            tool_calls=self.all_tool_calls,
            total_tokens=total_tokens,
            duration=duration,
            final_report=final_report,
        )

        if tracer:
            # Build a conversation transcript so the judge can see
            # requester messages (critical for behavior classification).
            convo_lines = []
            for t in turns:
                label = "REQUESTER" if t.role == "requester" else "AGENT"
                snippet = t.content[:300] if t.content else ""
                convo_lines.append(f"[{label} Turn {t.turn_number}]: {snippet}")
            transcript = "\n".join(convo_lines)

            output_for_judge = (
                f"## Conversation Transcript\n{transcript}\n\n"
                f"## Final Report\n{final_report[:2000] if final_report else ''}"
            )
            tracer.set_output(output_for_judge[:5000])
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
