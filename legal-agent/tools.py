"""Simulated legal research tools using Claude Haiku for realistic content generation."""
import json
import re

import anthropic

from models import (
    CaseLawResult,
    StatuteResult,
    PrecedentResult,
    JurisdictionCheck,
    ContractClauseAnalysis,
)
from tracing import observe, wrap_client


client = None  # lazy init to avoid import-time failures
HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _get_client() -> anthropic.Anthropic:
    """Lazy-init the Anthropic client (auto-instrumented when tracing is on)."""
    global client
    if client is None:
        client = wrap_client(anthropic.Anthropic())
    return client


class TokenTracker:
    """Track token usage across tool calls."""

    def __init__(self):
        self.total_input = 0
        self.total_output = 0

    def add(self, usage):
        self.total_input += usage.input_tokens
        self.total_output += usage.output_tokens

    @property
    def total(self):
        return self.total_input + self.total_output

    def reset(self):
        self.total_input = 0
        self.total_output = 0


token_tracker = TokenTracker()
_haiku_consecutive_failures = 0
tools_degraded = False  # exported flag -- agent checks this to disable tools


def _parse_json(text: str):
    """Parse JSON from an LLM response, handling markdown code blocks."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    for pattern in [r"\[.*\]", r"\{.*\}"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Could not parse JSON from response: {text[:300]}")


@observe(span_type="llm")
def _call_haiku(prompt: str, max_tokens: int = 3000) -> str:
    """Call Claude Haiku and track tokens. Raises on failure with a clear message."""
    global _haiku_consecutive_failures, tools_degraded

    if tools_degraded:
        raise RuntimeError("Tools degraded -- skipping Haiku call")

    c = _get_client()
    try:
        response = c.messages.create(
            model=HAIKU_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        token_tracker.add(response.usage)
        _haiku_consecutive_failures = 0
        return response.content[0].text
    except Exception as e:
        _haiku_consecutive_failures += 1
        if _haiku_consecutive_failures <= 3:
            print(f"  [tools] Haiku call failed ({type(e).__name__}): {e}")
        if _haiku_consecutive_failures >= 3:
            tools_degraded = True
            print("  [tools] 3 consecutive failures -- disabling tool LLM calls for this session")
        raise


@observe(span_type="tool")
def search_case_law(query: str, jurisdiction: str) -> list[CaseLawResult]:
    """Search case law databases for relevant cases."""
    prompt = f"""Generate 4 realistic case law search results for: "{query}" in {jurisdiction} jurisdiction.
JSON array. Each object: "case_name" (realistic party names v. party names), "citation" (realistic reporter citation e.g. "523 U.S. 44"), "court" (specific court name), "year" (1990-2025), "holding" (2 sentences), "relevance" (supports|opposes|distinguishable, vary these), "key_quote" (1 sentence from the opinion).
JSON only."""
    try:
        raw = _call_haiku(prompt, max_tokens=1500)
        data = _parse_json(raw)
        return [CaseLawResult(**item) for item in data]
    except Exception:
        return [
            CaseLawResult(
                case_name=f"Relevant Case re: {query[:40]}",
                citation="No. 24-1234",
                court=f"{jurisdiction} Court",
                year=2024,
                holding=f"The court addressed issues related to {query}.",
                relevance="supports",
                key_quote="The court found the argument persuasive.",
            )
        ]


@observe(span_type="tool")
def read_statute(statute_reference: str, jurisdiction: str) -> StatuteResult:
    """Read and extract content from a statute or regulation."""
    prompt = f"""Extract structured content from statute: {statute_reference} in {jurisdiction}.
JSON object: "title" (full statute title), "section" (specific section number), "jurisdiction": "{jurisdiction}", "summary" (3 sentences explaining the provision), "effective_date" (YYYY-MM-DD), "relevance_note" (1 sentence on applicability).
JSON only."""
    try:
        raw = _call_haiku(prompt, max_tokens=1000)
        data = _parse_json(raw)
        data["jurisdiction"] = jurisdiction
        return StatuteResult(**data)
    except Exception:
        return StatuteResult(
            title=statute_reference,
            section="General",
            jurisdiction=jurisdiction,
            summary=f"Statutory provision addressing {statute_reference}.",
            effective_date="2024-01-01",
            relevance_note="Applicable to the matter under review.",
        )


@observe(span_type="tool")
def find_legal_precedents(legal_issue: str, area_of_law: str) -> list[PrecedentResult]:
    """Find relevant legal precedents for a specific legal issue."""
    prompt = f"""Generate 3 realistic legal precedent results for "{legal_issue}" in {area_of_law}.
JSON array. Each: "case_name" (realistic), "citation" (realistic reporter citation), "court" (specific court), "year" (1985-2025), "legal_principle" (2 sentences), "how_applied" (1 sentence on how courts apply this), "subsequent_treatment" (followed|distinguished|overruled|cited, vary these).
JSON only."""
    try:
        raw = _call_haiku(prompt, max_tokens=1500)
        data = _parse_json(raw)
        return [PrecedentResult(**item) for item in data]
    except Exception:
        return [
            PrecedentResult(
                case_name=f"Precedent re: {legal_issue[:40]}",
                citation="No. 23-5678",
                court="U.S. Court of Appeals",
                year=2023,
                legal_principle=f"Established framework for {legal_issue}.",
                how_applied="Courts routinely apply this standard.",
                subsequent_treatment="followed",
            )
        ]


@observe(span_type="tool")
def check_jurisdiction(issue: str, jurisdictions: list[str]) -> JurisdictionCheck:
    """Verify jurisdictional applicability for a legal matter."""
    juris_str = ", ".join(jurisdictions)
    prompt = f"""Analyze jurisdiction for: "{issue}" across {juris_str}.
JSON object: "jurisdiction" (primary applicable jurisdiction), "applicable" (true/false), "governing_law" (which body of law applies), "key_considerations" (3 strings about jurisdictional factors), "conflicts_of_law" (1-2 strings about potential conflicts), "forum_selection_notes" (1 sentence).
JSON only."""
    try:
        raw = _call_haiku(prompt, max_tokens=800)
        data = _parse_json(raw)
        return JurisdictionCheck(**data)
    except Exception:
        return JurisdictionCheck(
            jurisdiction=jurisdictions[0] if jurisdictions else "Federal",
            applicable=True,
            governing_law="State and federal law",
            key_considerations=["Jurisdictional analysis pending"],
            conflicts_of_law=[],
            forum_selection_notes="Further analysis required.",
        )


@observe(span_type="tool")
def analyze_contract_clause(clause_text: str, analysis_type: str) -> ContractClauseAnalysis:
    """Analyze a specific contract clause for risks and enforceability."""
    prompt = f"""Analyze this contract clause ({analysis_type} analysis):
"{clause_text}"
JSON object: "clause_text": "{clause_text[:100]}...", "analysis_type": "{analysis_type}", "risk_level" (low|medium|high|critical), "issues_found" (3 strings), "recommendations" (2 strings), "enforceability_notes" (2 sentences).
JSON only."""
    try:
        raw = _call_haiku(prompt, max_tokens=800)
        data = _parse_json(raw)
        data["clause_text"] = clause_text
        data["analysis_type"] = analysis_type
        return ContractClauseAnalysis(**data)
    except Exception:
        return ContractClauseAnalysis(
            clause_text=clause_text,
            analysis_type=analysis_type,
            risk_level="medium",
            issues_found=["Clause requires further review"],
            recommendations=["Consider revision"],
            enforceability_notes="Enforceability depends on jurisdiction.",
        )


@observe(span_type="tool")
def draft_legal_section(topic: str, sources: list[str], format: str) -> str:
    """Draft a section of a legal memo or brief from sources."""
    sources_text = "\n".join(f"- {s}" for s in sources[:6])
    prompt = f"""Draft a {format} legal section on "{topic}" using these sources:
{sources_text}
Cite cases and statutes properly (e.g., Smith v. Jones, 523 U.S. 44 (2005)). Be substantive, analytical, and use proper legal writing style. Include relevant legal standards and tests."""
    try:
        return _call_haiku(prompt, max_tokens=1200)
    except Exception:
        return f"Section on {topic}: Further legal analysis pending."
