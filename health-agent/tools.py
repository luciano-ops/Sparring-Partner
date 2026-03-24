"""Simulated health research tools using Claude Haiku for realistic content generation."""

import json
import re

import anthropic

from models import (
    SearchResult,
    ClinicalStudy,
    GuidelineResult,
    DrugInteractionResult,
    ClinicalDataAnalysis,
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
def search_medical_literature(query: str, search_type: str) -> list[SearchResult]:
    """Search medical databases (PubMed, Cochrane, etc.) returning 3-5 results."""
    prompt = f"""Generate 4 realistic {search_type} medical literature search results for: "{query}"
JSON array. Each object: "title", "url" (realistic PubMed/Cochrane/WHO URLs), "snippet" (2 sentences), "source_type" (clinical_trial|systematic_review|meta_analysis|case_study|guidelines|epidemiological_study), "credibility_score" (0-1, vary: include <0.5 and >0.8), "published_date" (YYYY-MM-DD, vary dates 2020-2025).
JSON only."""
    try:
        raw = _call_haiku(prompt, max_tokens=1500)
        data = _parse_json(raw)
        return [SearchResult(**item) for item in data]
    except Exception:
        return [
            SearchResult(
                title=f"Medical literature result for: {query}",
                url=f"https://pubmed.ncbi.nlm.nih.gov/{hash(query) % 99999999}",
                snippet=f"Relevant clinical findings about {query}.",
                source_type="clinical_trial",
                credibility_score=0.7,
                published_date="2024-06-15",
            )
        ]


@observe(span_type="tool")
def read_clinical_study(url: str) -> ClinicalStudy:
    """Read and extract structured content from a clinical study."""
    prompt = f"""Extract structured content from this clinical study: {url}
JSON object: "title", "url": "{url}", "study_type" (RCT|cohort|case_control|cross_sectional|systematic_review|meta_analysis), "publication_date" (YYYY-MM-DD), "credibility_score" (0-1), "summary" (3 sentences about methodology and results), "key_findings" (3 strings with specific clinical outcomes and statistics), "limitations" (2 strings).
JSON only."""
    try:
        raw = _call_haiku(prompt, max_tokens=1000)
        data = _parse_json(raw)
        data["url"] = url
        return ClinicalStudy(**data)
    except Exception:
        return ClinicalStudy(
            title=f"Clinical study from {url}",
            url=url,
            study_type="RCT",
            publication_date="2024-03-15",
            credibility_score=0.7,
            summary=f"Clinical findings extracted from {url}.",
            key_findings=["Primary endpoint met with statistical significance"],
            limitations=["Single-center study with limited sample size"],
        )


@observe(span_type="tool")
def find_treatment_guidelines(condition: str, specialty: str) -> list[GuidelineResult]:
    """Find relevant clinical practice guidelines from major medical bodies."""
    prompt = f"""Generate 3 realistic clinical practice guidelines for "{condition}" in {specialty}.
JSON array. Each: "title", "issuing_body" (e.g. AHA, WHO, NICE, ACS, IDSA, ACOG), "year" (2020-2025), "recommendation_grade" (A|B|C|D|I), "key_recommendations" (3 strings with specific clinical guidance), "evidence_level" (high|moderate|low|very_low), "url" (realistic guideline URL).
JSON only."""
    try:
        raw = _call_haiku(prompt, max_tokens=1500)
        data = _parse_json(raw)
        return [GuidelineResult(**item) for item in data]
    except Exception:
        return [
            GuidelineResult(
                title=f"Clinical guidelines for {condition}",
                issuing_body="WHO",
                year=2024,
                recommendation_grade="B",
                key_recommendations=[f"Standard treatment protocol for {condition}"],
                evidence_level="moderate",
                url=f"https://www.who.int/guidelines/{condition.lower().replace(' ', '-')}",
            )
        ]


@observe(span_type="tool")
def check_drug_interactions(drug_a: str, drug_b: str) -> DrugInteractionResult:
    """Check for drug-drug interactions and contraindications."""
    prompt = f"""Check drug interaction between "{drug_a}" and "{drug_b}".
JSON object: "drug_a": "{drug_a}", "drug_b": "{drug_b}", "severity" (major|moderate|minor|none), "mechanism" (1-2 sentences about pharmacological mechanism), "clinical_significance" (2 sentences about clinical impact), "management_recommendation" (2 sentences about how to manage), "evidence_quality" (strong|moderate|limited|theoretical).
JSON only."""
    try:
        raw = _call_haiku(prompt, max_tokens=800)
        data = _parse_json(raw)
        data["drug_a"] = drug_a
        data["drug_b"] = drug_b
        return DrugInteractionResult(**data)
    except Exception:
        return DrugInteractionResult(
            drug_a=drug_a,
            drug_b=drug_b,
            severity="moderate",
            mechanism="Interaction mechanism requires further evaluation.",
            clinical_significance="Clinical significance to be determined.",
            management_recommendation="Monitor patient closely and adjust dosing as needed.",
            evidence_quality="limited",
        )


@observe(span_type="tool")
def analyze_clinical_data(dataset_description: str, analysis_type: str) -> ClinicalDataAnalysis:
    """Analyze clinical or epidemiological datasets."""
    prompt = f"""Analyze clinical dataset: "{dataset_description}" ({analysis_type} analysis)
JSON object: "dataset_description": "{dataset_description}", "analysis_type": "{analysis_type}", "findings" (3 strings with specific clinical/epidemiological findings), "key_statistics" (3 numeric key-value pairs like NNT, RR, OR, HR, incidence rates), "confidence_intervals" (2 string key-value pairs), "chart_description" (1 sentence describing a relevant clinical chart), "methodology_notes" (1 sentence about statistical methods used).
JSON only."""
    try:
        raw = _call_haiku(prompt, max_tokens=800)
        data = _parse_json(raw)
        data["dataset_description"] = dataset_description
        data["analysis_type"] = analysis_type
        return ClinicalDataAnalysis(**data)
    except Exception:
        return ClinicalDataAnalysis(
            dataset_description=dataset_description,
            analysis_type=analysis_type,
            findings=[f"Analysis of {dataset_description} shows notable clinical trends."],
            key_statistics={"sample_size": 5000.0, "relative_risk": 1.45},
            confidence_intervals={"primary": "95% CI [1.12, 1.88]"},
            chart_description=f"A {analysis_type} chart showing clinical outcome trends.",
            methodology_notes=f"Standard {analysis_type} analysis with Cox regression applied.",
        )


@observe(span_type="tool")
def draft_clinical_section(topic: str, sources: list[str], format: str) -> str:
    """Draft a section of a clinical report or summary."""
    sources_text = "\n".join(f"- {s}" for s in sources[:6])
    prompt = f"""Write a {format} clinical report section on "{topic}" using these sources:
{sources_text}
Cite sources as [1], [2], etc. Be evidence-based, cite specific studies and statistics.
Use appropriate medical terminology. Include risk-benefit considerations."""
    try:
        return _call_haiku(prompt, max_tokens=1200)
    except Exception:
        return f"Section on {topic}: Further clinical evidence review pending."
