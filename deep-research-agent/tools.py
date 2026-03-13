"""Simulated research tools using Claude Haiku for realistic content generation."""

import json
import os
import re
import time

import anthropic

from models import (
    SearchResult,
    SourceDocument,
    PaperResult,
    FactCheckResult,
    DataAnalysis,
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
tools_degraded = False  # exported flag — agent checks this to disable tools


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

    # If tools have been marked degraded, skip the API call entirely
    if tools_degraded:
        raise RuntimeError("Tools degraded — skipping Haiku call")

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
            print("  [tools] 3 consecutive failures — disabling tool LLM calls for this session")
        raise


@observe(span_type="tool")
def web_search(query: str, search_type: str) -> list[SearchResult]:
    """Simulate a web search returning 3-6 results with mixed credibility."""
    prompt = f"""Generate 4 realistic {search_type} web search results for: "{query}"

JSON array. Each object: "title", "url" (fake but realistic), "snippet" (2 sentences), "source_type" (academic_paper|news_article|government_report|blog|whitepaper|dataset), "credibility_score" (0-1, vary: include <0.5 and >0.8), "published_date" (YYYY-MM-DD, vary dates).

JSON only."""

    try:
        raw = _call_haiku(prompt, max_tokens=1500)
        data = _parse_json(raw)
        return [SearchResult(**item) for item in data]
    except Exception:
        return [
            SearchResult(
                title=f"Search result for: {query}",
                url=f"https://www.example.com/search/{query.replace(' ', '-')}",
                snippet=f"Relevant information about {query}.",
                source_type="news_article",
                credibility_score=0.7,
                published_date="2025-01-15",
            )
        ]


@observe(span_type="tool")
def read_source(url: str) -> SourceDocument:
    """Simulate reading and extracting content from a source URL."""
    prompt = f"""Extract structured content from: {url}

JSON object: "title", "url": "{url}", "source_type" (academic_paper|news_article|government_report|blog|whitepaper|dataset), "publication_date" (YYYY-MM-DD), "credibility_score" (0-1), "summary" (3 sentences), "key_findings" (3 strings), "potential_biases" (1-2 strings).

JSON only."""

    try:
        raw = _call_haiku(prompt, max_tokens=1000)
        data = _parse_json(raw)
        data["url"] = url
        return SourceDocument(**data)
    except Exception:
        return SourceDocument(
            title=f"Document from {url}",
            url=url,
            source_type="news_article",
            publication_date="2025-01-15",
            credibility_score=0.6,
            summary=f"Content extracted from {url}.",
            key_findings=["Finding 1", "Finding 2"],
            potential_biases=["Source bias not assessed"],
        )


@observe(span_type="tool")
def find_academic_papers(query: str, field: str) -> list[PaperResult]:
    """Simulate an academic paper search returning 2-5 papers."""
    prompt = f"""Generate 3 realistic academic papers for "{query}" in {field}.

JSON array. Each: "title", "authors" (2-3 names), "journal", "year" (2018-2025), "abstract" (2 sentences), "citation_count", "key_conclusions" (2 strings), "doi" (10.xxxx/...).

JSON only."""

    try:
        raw = _call_haiku(prompt, max_tokens=1500)
        data = _parse_json(raw)
        return [PaperResult(**item) for item in data]
    except Exception:
        return [
            PaperResult(
                title=f"A Study on {query}",
                authors=["Smith, J.", "Chen, L."],
                journal=f"Journal of {field}",
                year=2024,
                abstract=f"This paper examines {query}.",
                citation_count=12,
                key_conclusions=[f"Key finding related to {query}"],
                doi="10.1234/example.2024.00001",
            )
        ]


@observe(span_type="tool")
def check_facts(claim: str, context: str) -> FactCheckResult:
    """Simulate fact-checking a specific claim."""
    prompt = f"""Fact-check: "{claim}" (context: {context})

JSON object: "claim": "{claim}", "status" (verified|partially_true|unverified|false|disputed), "confidence" (0-1), "supporting_evidence" (2 strings), "contradicting_evidence" (1 string or empty), "sources_checked" (3-8).

JSON only."""

    try:
        raw = _call_haiku(prompt, max_tokens=800)
        data = _parse_json(raw)
        data["claim"] = claim
        return FactCheckResult(**data)
    except Exception:
        return FactCheckResult(
            claim=claim,
            status="unverified",
            confidence=0.5,
            supporting_evidence=["Limited evidence available"],
            contradicting_evidence=[],
            sources_checked=3,
        )


@observe(span_type="tool")
def analyze_data(dataset_description: str, analysis_type: str) -> DataAnalysis:
    """Simulate data analysis on a described dataset."""
    prompt = f"""Analyze dataset: "{dataset_description}" ({analysis_type} analysis)

JSON object: "dataset_description": "{dataset_description}", "analysis_type": "{analysis_type}", "findings" (3 strings), "key_statistics" (3 numeric key-value pairs), "confidence_intervals" (2 string key-value pairs), "chart_description" (1 sentence), "methodology_notes" (1 sentence).

JSON only."""

    try:
        raw = _call_haiku(prompt, max_tokens=800)
        data = _parse_json(raw)
        data["dataset_description"] = dataset_description
        data["analysis_type"] = analysis_type
        return DataAnalysis(**data)
    except Exception:
        return DataAnalysis(
            dataset_description=dataset_description,
            analysis_type=analysis_type,
            findings=[f"Analysis of {dataset_description} shows notable trends."],
            key_statistics={"sample_size": 1000.0, "mean": 50.0},
            confidence_intervals={"primary": "95% CI [45.0, 55.0]"},
            chart_description=f"A {analysis_type} chart showing trends in the data.",
            methodology_notes=f"Standard {analysis_type} analysis applied.",
        )


@observe(span_type="tool")
def synthesize_section(topic: str, sources: list[str], format: str) -> str:
    """Synthesize a research report section from sources."""
    sources_text = "\n".join(f"- {s}" for s in sources[:6])  # cap source input
    prompt = f"""Write a {format} section on "{topic}" using these sources:
{sources_text}

Cite sources as [1], [2], etc. Be substantive and analytical."""

    try:
        return _call_haiku(prompt, max_tokens=1200)
    except Exception:
        return f"Section on {topic}: Further analysis pending."
