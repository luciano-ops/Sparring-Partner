"""Pydantic models for the deep research agent."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class ResearchType(str, Enum):
    LITERATURE_REVIEW = "Literature_Review"
    MARKET_ANALYSIS = "Market_Analysis"
    TECHNICAL_DEEP_DIVE = "Technical_Deep_Dive"
    FACT_CHECKING = "Fact_Checking"
    COMPARATIVE_ANALYSIS = "Comparative_Analysis"
    TREND_RESEARCH = "Trend_Research"


class Complexity(str, Enum):
    SIMPLE = "Simple"
    MODERATE = "Moderate"
    COMPLEX = "Complex"
    EXPERT_LEVEL = "Expert_Level"


class TimeSensitivity(str, Enum):
    HISTORICAL = "Historical"
    CURRENT = "Current"
    BREAKING = "Breaking"
    EVERGREEN = "Evergreen"


class RequesterPersona(str, Enum):
    EXECUTIVE = "Executive"
    ACADEMIC = "Academic"
    JOURNALIST = "Journalist"
    STUDENT = "Student"
    ANALYST = "Analyst"
    CURIOUS_GENERALIST = "Curious_Generalist"


class DepthPreference(str, Enum):
    OVERVIEW = "Overview"
    DETAILED = "Detailed"
    EXHAUSTIVE = "Exhaustive"


class QueryProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    research_type: ResearchType
    domain: str
    complexity: Complexity
    query: str
    sub_questions: list[str] = []
    expected_sources: int = 5
    time_sensitivity: TimeSensitivity = TimeSensitivity.CURRENT
    requester_persona: RequesterPersona = RequesterPersona.ANALYST
    depth_preference: DepthPreference = DepthPreference.DETAILED
    edge_case_tags: list[str] = []


# --- Tool result models ---


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    source_type: str
    credibility_score: float
    published_date: str


class SourceDocument(BaseModel):
    title: str
    url: str
    source_type: str
    publication_date: str
    credibility_score: float
    summary: str
    key_findings: list[str]
    potential_biases: list[str]


class PaperResult(BaseModel):
    title: str
    authors: list[str]
    journal: str
    year: int
    abstract: str
    citation_count: int
    key_conclusions: list[str]
    doi: str


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    PARTIALLY_TRUE = "partially_true"
    UNVERIFIED = "unverified"
    FALSE = "false"
    DISPUTED = "disputed"


class FactCheckResult(BaseModel):
    claim: str
    status: VerificationStatus
    confidence: float
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    sources_checked: int


class DataAnalysis(BaseModel):
    dataset_description: str
    analysis_type: str
    findings: list[str]
    key_statistics: dict[str, float]
    confidence_intervals: dict[str, str]
    chart_description: str
    methodology_notes: str


# --- Trace models ---


class ToolCall(BaseModel):
    tool_name: str
    inputs: dict
    output: str
    duration: float
    tokens_used: int


class ConversationTurn(BaseModel):
    turn_number: int
    role: str  # "requester" or "agent"
    content: str
    tool_calls: list[ToolCall] = []
    timestamp: float


class ResearchTrace(BaseModel):
    profile_id: str
    profile: QueryProfile
    turns: list[ConversationTurn] = []
    tool_calls: list[ToolCall] = []
    total_tokens: int = 0
    duration: float = 0.0
    final_report: Optional[str] = None
