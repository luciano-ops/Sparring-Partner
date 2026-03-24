"""Pydantic models for the legal research agent."""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class LegalResearchType(str, Enum):
    CASE_LAW_RESEARCH = "Case_Law_Research"
    STATUTORY_ANALYSIS = "Statutory_Analysis"
    CONTRACT_REVIEW = "Contract_Review"
    DUE_DILIGENCE = "Due_Diligence"
    REGULATORY_ASSESSMENT = "Regulatory_Assessment"
    LEGAL_MEMORANDUM = "Legal_Memorandum"


class Complexity(str, Enum):
    SIMPLE = "Simple"
    MODERATE = "Moderate"
    COMPLEX = "Complex"
    EXPERT_LEVEL = "Expert_Level"


class TimeSensitivity(str, Enum):
    HISTORICAL = "Historical"
    CURRENT = "Current"
    URGENT = "Urgent"
    ONGOING = "Ongoing"


class RequesterPersona(str, Enum):
    GENERAL_COUNSEL = "General_Counsel"
    ASSOCIATE_ATTORNEY = "Associate_Attorney"
    PARALEGAL = "Paralegal"
    BUSINESS_EXECUTIVE = "Business_Executive"
    COMPLIANCE_OFFICER = "Compliance_Officer"
    LAW_STUDENT = "Law_Student"


class DepthPreference(str, Enum):
    OVERVIEW = "Overview"
    DETAILED = "Detailed"
    EXHAUSTIVE = "Exhaustive"


class QueryProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    research_type: LegalResearchType
    domain: str
    complexity: Complexity
    query: str
    sub_questions: list[str] = []
    expected_sources: int = 5
    time_sensitivity: TimeSensitivity = TimeSensitivity.CURRENT
    requester_persona: RequesterPersona = RequesterPersona.ASSOCIATE_ATTORNEY
    depth_preference: DepthPreference = DepthPreference.DETAILED
    edge_case_tags: list[str] = []


# --- Tool result models ---

class CaseLawResult(BaseModel):
    case_name: str
    citation: str
    court: str
    year: int
    holding: str
    relevance: str  # "supports" | "opposes" | "distinguishable"
    key_quote: str


class StatuteResult(BaseModel):
    title: str
    section: str
    jurisdiction: str
    summary: str
    effective_date: str
    relevance_note: str


class PrecedentResult(BaseModel):
    case_name: str
    citation: str
    court: str
    year: int
    legal_principle: str
    how_applied: str
    subsequent_treatment: str  # "followed" | "distinguished" | "overruled" | "cited"


class JurisdictionCheck(BaseModel):
    jurisdiction: str
    applicable: bool
    governing_law: str
    key_considerations: list[str]
    conflicts_of_law: list[str]
    forum_selection_notes: str


class ContractClauseAnalysis(BaseModel):
    clause_text: str
    analysis_type: str
    risk_level: str  # "low" | "medium" | "high" | "critical"
    issues_found: list[str]
    recommendations: list[str]
    enforceability_notes: str


class LegalSectionDraft(BaseModel):
    section_title: str
    content: str
    citations: list[str]
    confidence_level: str  # "high" | "medium" | "low"


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


class LegalResearchTrace(BaseModel):
    profile_id: str
    profile: QueryProfile
    turns: list[ConversationTurn] = []
    tool_calls: list[ToolCall] = []
    total_tokens: int = 0
    duration: float = 0.0
    final_report: Optional[str] = None
