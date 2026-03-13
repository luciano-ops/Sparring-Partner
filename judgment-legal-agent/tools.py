"""Simulated legal tools using Claude Haiku for realistic content generation.

Each tool is wrapped with a Judgment tracer span so individual tool calls
appear in the dashboard with full input/output capture.
"""

from __future__ import annotations

import functools
import json
from typing import Any

from instrumentation import get_wrapped_client, tracer
from models import (
    CaseResult,
    ComplianceResult,
    ContractAnalysis,
    LiabilityEstimate,
    StatuteResult,
)

HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Per-tool max output tokens — sized to typical output + 30% headroom.
# Prevents Haiku from generating more than the agent actually uses.
TOOL_MAX_TOKENS: dict[str, int] = {
    "search_case_law": 768,
    "search_statutes": 768,
    "analyze_contract_clause": 512,
    "check_compliance": 512,
    "calculate_liability": 512,
    "draft_memo": 1536,
}

# Single wrapped client for all tool LLM calls — matches health agent pattern.
# Creating a new wrapped client per call corrupts the Judgment trace context.
_haiku_client = get_wrapped_client()


def _llm_generate(system: str, prompt: str, max_tokens: int = 1024) -> str:
    """Call Claude Haiku to generate simulated legal content."""
    resp = _haiku_client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


# ── Tool definitions for Claude tool_use schema ───────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_case_law",
        "description": (
            "Search for relevant case law precedents. Returns 2-4 case citations "
            "with holdings, some supporting and some opposing the query position."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Legal question or issue to search for",
                },
                "jurisdiction": {
                    "type": "string",
                    "description": "Jurisdiction to search within (e.g. 'California', 'Federal - 9th Circuit')",
                },
            },
            "required": ["query", "jurisdiction"],
        },
    },
    {
        "name": "search_statutes",
        "description": (
            "Search for relevant statutes, regulations, and codes. Returns "
            "applicable statutory provisions with section numbers and summaries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Topic or legal issue to find statutes for",
                },
                "jurisdiction": {
                    "type": "string",
                    "description": "Jurisdiction to search within",
                },
            },
            "required": ["query", "jurisdiction"],
        },
    },
    {
        "name": "analyze_contract_clause",
        "description": (
            "Analyze a specific contract clause for risks, enforceability, "
            "or ambiguity. Returns detailed analysis with risk level and recommendations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "clause_text": {
                    "type": "string",
                    "description": "The contract clause text to analyze",
                },
                "analysis_type": {
                    "type": "string",
                    "enum": ["risk_assessment", "enforceability", "ambiguity_check"],
                    "description": "Type of analysis to perform",
                },
            },
            "required": ["clause_text", "analysis_type"],
        },
    },
    {
        "name": "check_compliance",
        "description": (
            "Check compliance with a specific regulation given a set of facts. "
            "Returns compliance status, gaps, and remediation steps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "regulation": {
                    "type": "string",
                    "description": "The regulation or standard to check against",
                },
                "facts": {
                    "type": "object",
                    "description": "Key facts about the situation to evaluate",
                },
            },
            "required": ["regulation", "facts"],
        },
    },
    {
        "name": "draft_memo",
        "description": (
            "Draft a legal memorandum, client letter, or brief summary on a "
            "given topic with specified key points."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Subject of the memo",
                },
                "key_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key points to cover",
                },
                "format": {
                    "type": "string",
                    "enum": ["client_letter", "internal_memo", "brief_summary"],
                    "description": "Format of the document to draft",
                },
            },
            "required": ["topic", "key_points", "format"],
        },
    },
    {
        "name": "calculate_liability",
        "description": (
            "Calculate potential liability exposure for a given claim type and "
            "facts. Returns exposure range, key factors, and risk assessment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "claim_type": {
                    "type": "string",
                    "description": "Type of legal claim (e.g. 'breach_of_contract', 'negligence', 'ip_infringement')",
                },
                "facts": {
                    "type": "object",
                    "description": "Key facts relevant to liability calculation",
                },
            },
            "required": ["claim_type", "facts"],
        },
    },
]


# ── Raw tool implementations ─────────────────────────────────────────────


def _search_case_law(query: str, jurisdiction: str) -> list[dict]:
    system = (
        "You are a legal research database. Return ONLY valid JSON — no markdown fences. "
        "Generate 2 realistic but fictional case law results as a JSON array. "
        "Each case should have: case_name, citation (realistic format like '123 F.3d 456'), "
        "year (2005-2024), court, holding (1-2 sentences), relevance ('supports'|'opposes'|'distinguishable'), "
        "key_quote (one sentence). One supporting and one opposing. Make them feel like real legal research."
    )
    prompt = f"Find case law for: {query}\nJurisdiction: {jurisdiction}"
    raw = _llm_generate(system, prompt, max_tokens=TOOL_MAX_TOKENS["search_case_law"])
    try:
        cases = json.loads(raw)
        return [CaseResult(**c).model_dump() for c in cases]
    except (json.JSONDecodeError, Exception):
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                cases = json.loads(raw[start:end])
                return [CaseResult(**c).model_dump() for c in cases]
            except Exception:
                pass
        return [
            CaseResult(
                case_name="Research Error",
                citation="N/A",
                year=2024,
                court=jurisdiction,
                holding=f"Case law search results for: {query}. {raw[:500]}",
                relevance="distinguishable",
                key_quote="See full analysis.",
            ).model_dump()
        ]


def _search_statutes(query: str, jurisdiction: str) -> list[dict]:
    system = (
        "You are a statutory database. Return ONLY valid JSON — no markdown fences. "
        "Generate 2-3 realistic but fictional statute results as a JSON array. "
        "Each statute should have: title, section (like '\u00a7 12-345'), jurisdiction, "
        "summary (2-3 sentences), effective_date (YYYY-MM-DD), relevance_note (one sentence). "
        "Make them realistic for the jurisdiction."
    )
    prompt = f"Find statutes for: {query}\nJurisdiction: {jurisdiction}"
    raw = _llm_generate(system, prompt, max_tokens=TOOL_MAX_TOKENS["search_statutes"])
    try:
        statutes = json.loads(raw)
        return [StatuteResult(**s).model_dump() for s in statutes]
    except (json.JSONDecodeError, Exception):
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                statutes = json.loads(raw[start:end])
                return [StatuteResult(**s).model_dump() for s in statutes]
            except Exception:
                pass
        return [
            StatuteResult(
                title="Statute Search",
                section="N/A",
                jurisdiction=jurisdiction,
                summary=f"Statutory search for: {query}. {raw[:500]}",
                effective_date="2024-01-01",
                relevance_note="See full text.",
            ).model_dump()
        ]


def _analyze_contract_clause(clause_text: str, analysis_type: str) -> dict:
    system = (
        "You are a contract analysis engine. Return ONLY valid JSON — no markdown fences. "
        "Analyze the given clause and return a JSON object with: "
        "risk_level ('low'|'medium'|'high'|'critical'), "
        "issues_found (array of 2-4 strings), recommendations (array of 2-3 strings), "
        "enforceability_notes (1-2 sentences). Be thorough and realistic."
    )
    prompt = f"Analyze this clause ({analysis_type}):\n{clause_text}"
    raw = _llm_generate(system, prompt, max_tokens=TOOL_MAX_TOKENS["analyze_contract_clause"])
    try:
        result = json.loads(raw)
        result["clause_text"] = clause_text
        result["analysis_type"] = analysis_type
        return ContractAnalysis(**result).model_dump()
    except (json.JSONDecodeError, Exception):
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(raw[start:end])
                result["clause_text"] = clause_text
                result["analysis_type"] = analysis_type
                return ContractAnalysis(**result).model_dump()
            except Exception:
                pass
        return ContractAnalysis(
            clause_text=clause_text,
            analysis_type=analysis_type,
            risk_level="medium",
            issues_found=[f"Analysis result: {raw[:300]}"],
            recommendations=["Review with senior counsel"],
            enforceability_notes="Further analysis recommended.",
        ).model_dump()


def _check_compliance(regulation: str, facts: dict) -> dict:
    system = (
        "You are a compliance checking engine. Return ONLY valid JSON — no markdown fences. "
        "Return a JSON object with: "
        "status ('compliant'|'non_compliant'|'partially_compliant'|'unclear'), "
        "gaps (array of 2-4 strings), remediation_steps (array of 2-3 strings), "
        "risk_if_unaddressed (1-2 sentences). Be specific and actionable."
    )
    prompt = f"Check compliance with: {regulation}\nFacts: {json.dumps(facts)}"
    raw = _llm_generate(system, prompt, max_tokens=TOOL_MAX_TOKENS["check_compliance"])
    try:
        result = json.loads(raw)
        result["regulation"] = regulation
        return ComplianceResult(**result).model_dump()
    except (json.JSONDecodeError, Exception):
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(raw[start:end])
                result["regulation"] = regulation
                return ComplianceResult(**result).model_dump()
            except Exception:
                pass
        return ComplianceResult(
            regulation=regulation,
            status="unclear",
            gaps=[f"Compliance check result: {raw[:300]}"],
            remediation_steps=["Engage compliance counsel for detailed review"],
            risk_if_unaddressed="Potential regulatory exposure if gaps remain unaddressed.",
        ).model_dump()


def _draft_memo(topic: str, key_points: list[str], format: str) -> str:
    format_instructions = {
        "client_letter": "Draft a professional client advisory letter. Use formal but accessible language.",
        "internal_memo": "Draft an internal legal memorandum with Analysis and Recommendation sections.",
        "brief_summary": "Draft a concise executive brief (3-4 paragraphs max).",
    }
    system = (
        f"You are a legal drafting assistant. {format_instructions.get(format, '')} "
        "Write the document directly — no JSON wrapping. Use professional legal language."
    )
    prompt = f"Topic: {topic}\nKey points to address:\n" + "\n".join(
        f"- {p}" for p in key_points
    )
    return _llm_generate(system, prompt, max_tokens=TOOL_MAX_TOKENS["draft_memo"])


def _calculate_liability(claim_type: str, facts: dict) -> dict:
    system = (
        "You are a liability assessment engine. Return ONLY valid JSON — no markdown fences. "
        "Return a JSON object with: "
        "exposure_low (integer, dollars), exposure_high (integer, dollars), "
        "key_factors (array of 3-4 strings), "
        "risk_assessment (2-3 sentences), "
        "mitigating_factors (array of 2-3 strings), "
        "aggravating_factors (array of 2-3 strings). Be realistic about dollar amounts."
    )
    prompt = f"Calculate liability for: {claim_type}\nFacts: {json.dumps(facts)}"
    raw = _llm_generate(system, prompt, max_tokens=TOOL_MAX_TOKENS["calculate_liability"])
    try:
        result = json.loads(raw)
        result["claim_type"] = claim_type
        return LiabilityEstimate(**result).model_dump()
    except (json.JSONDecodeError, Exception):
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(raw[start:end])
                result["claim_type"] = claim_type
                return LiabilityEstimate(**result).model_dump()
            except Exception:
                pass
        return LiabilityEstimate(
            claim_type=claim_type,
            exposure_low=50000,
            exposure_high=500000,
            key_factors=[f"Liability analysis: {raw[:300]}"],
            risk_assessment="Moderate risk based on available facts. Further analysis recommended.",
            mitigating_factors=["Potential defenses available"],
            aggravating_factors=["Factual complexity increases risk"],
        ).model_dump()


# ── Traced tool wrappers ──────────────────────────────────────────────────


def _traced_tool(name: str, fn):
    """Wrap a tool function with its own named Judgment span.

    Each tool call appears as a separate span in the Judgment dashboard
    (e.g., 'search_case_law', 'analyze_contract_clause') with full input/output.
    """
    @tracer.observe(span_name=name, span_type="tool")
    @functools.wraps(fn)
    def wrapper(**kwargs):
        return fn(**kwargs)
    return wrapper


_RAW_TOOLS = {
    "search_case_law": _search_case_law,
    "search_statutes": _search_statutes,
    "analyze_contract_clause": _analyze_contract_clause,
    "check_compliance": _check_compliance,
    "draft_memo": _draft_memo,
    "calculate_liability": _calculate_liability,
}

# Each tool gets its own named span in Judgment
TOOL_MAP = {name: _traced_tool(name, fn) for name, fn in _RAW_TOOLS.items()}


def execute_tool(name: str, inputs: dict[str, Any]) -> str:
    """Execute a tool by name and return JSON string result.

    Individual tool tracing is handled by _traced_tool wrappers above —
    each tool appears as its own named span in Judgment.
    """
    handler = TOOL_MAP.get(name)
    if handler is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = handler(**inputs)
        if isinstance(result, str):
            return result
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Tool execution failed: {str(e)}"})
