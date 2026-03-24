"""Pydantic models for the health research agent."""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class ResearchType(str, Enum):
    CLINICAL_EVIDENCE_REVIEW = "Clinical_Evidence_Review"
    DRUG_INTERACTION_ANALYSIS = "Drug_Interaction_Analysis"
    EPIDEMIOLOGICAL_ASSESSMENT = "Epidemiological_Assessment"
    TREATMENT_PROTOCOL_COMPARISON = "Treatment_Protocol_Comparison"
    REGULATORY_FDA_ANALYSIS = "Regulatory_FDA_Analysis"
    HEALTH_POLICY_EVALUATION = "Health_Policy_Evaluation"


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
    PHYSICIAN = "Physician"
    HOSPITAL_ADMINISTRATOR = "Hospital_Administrator"
    PHARMACEUTICAL_RESEARCHER = "Pharmaceutical_Researcher"
    PUBLIC_HEALTH_OFFICIAL = "Public_Health_Official"
    PATIENT_ADVOCATE = "Patient_Advocate"
    MEDICAL_STUDENT = "Medical_Student"


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
    requester_persona: RequesterPersona = RequesterPersona.PHYSICIAN
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


class ClinicalStudy(BaseModel):
    title: str
    url: str
    study_type: str
    publication_date: str
    credibility_score: float
    summary: str
    key_findings: list[str]
    limitations: list[str]


class GuidelineResult(BaseModel):
    title: str
    issuing_body: str
    year: int
    recommendation_grade: str
    key_recommendations: list[str]
    evidence_level: str
    url: str


class DrugInteractionResult(BaseModel):
    drug_a: str
    drug_b: str
    severity: str
    mechanism: str
    clinical_significance: str
    management_recommendation: str
    evidence_quality: str


class ClinicalDataAnalysis(BaseModel):
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


class HealthResearchTrace(BaseModel):
    profile_id: str
    profile: QueryProfile
    turns: list[ConversationTurn] = []
    tool_calls: list[ToolCall] = []
    total_tokens: int = 0
    duration: float = 0.0
    final_report: Optional[str] = None
