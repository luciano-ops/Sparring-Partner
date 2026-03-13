"""Pydantic models for the legal AI agent."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────

class CaseType(str, Enum):
    Contract_Review = "Contract_Review"
    IP_Dispute = "IP_Dispute"
    Employment = "Employment"
    MandA_Due_Diligence = "MandA_Due_Diligence"
    Regulatory_Compliance = "Regulatory_Compliance"
    Litigation = "Litigation"


class Complexity(str, Enum):
    Routine = "Routine"
    Moderate = "Moderate"
    Complex = "Complex"
    High_Stakes = "High_Stakes"


class CommunicationStyle(str, Enum):
    Executive_Brief = "Executive_Brief"
    Detail_Oriented = "Detail_Oriented"
    Anxious = "Anxious"
    Adversarial = "Adversarial"
    Cooperative = "Cooperative"


class Urgency(str, Enum):
    Immediate = "Immediate"
    This_Week = "This_Week"
    Standard = "Standard"
    Advisory = "Advisory"


class EmotionalArc(str, Enum):
    Anxious = "Anxious"
    Confused = "Confused"
    Demanding = "Demanding"
    Neutral = "Neutral"
    Cooperative = "Cooperative"


# ── Document & Case Profile ───────────────────────────────────────────────

class Document(BaseModel):
    title: str
    doc_type: str  # contract, filing, correspondence, statute
    summary: str
    key_clauses: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)


class CaseProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    case_type: CaseType
    jurisdiction: str
    client_industry: str
    complexity: Complexity
    legal_issue: str
    key_facts: list[str]
    documents: list[Document] = Field(default_factory=list)
    opposing_party: str
    communication_style: CommunicationStyle
    urgency: Urgency
    edge_case_tags: list[str] = Field(default_factory=list)


# ── Tool Result Models ─────────────────────────────────────────────────────

class CaseResult(BaseModel):
    case_name: str
    citation: str
    year: int
    court: str
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


class ContractAnalysis(BaseModel):
    clause_text: str
    analysis_type: str
    risk_level: str  # "low" | "medium" | "high" | "critical"
    issues_found: list[str]
    recommendations: list[str]
    enforceability_notes: str


class ComplianceResult(BaseModel):
    regulation: str
    status: str  # "compliant" | "non_compliant" | "partially_compliant" | "unclear"
    gaps: list[str]
    remediation_steps: list[str]
    risk_if_unaddressed: str


class LiabilityEstimate(BaseModel):
    claim_type: str
    exposure_low: int
    exposure_high: int
    key_factors: list[str]
    risk_assessment: str
    mitigating_factors: list[str]
    aggravating_factors: list[str]


# ── Conversation Trace Models ──────────────────────────────────────────────

class ToolCall(BaseModel):
    tool_name: str
    tool_input: dict[str, Any]
    tool_result: str


class ConversationTurn(BaseModel):
    role: str  # "client" | "agent"
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
