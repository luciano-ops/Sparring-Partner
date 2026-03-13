from __future__ import annotations
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional


class CommunicationStyle(str, Enum):
    MEDICAL_LITERATE = "medical_literate"
    VAGUE = "vague"
    ANXIOUS = "anxious"
    MATTER_OF_FACT = "matter_of_fact"
    RAMBLING = "rambling"


class AgentMode(str, Enum):
    TRIAGE = "triage"
    INTAKE = "intake"
    LAB_REVIEW = "lab_review"


class UrgencyLevel(int, Enum):
    EMERGENCY = 1
    URGENT = 2
    SEMI_URGENT = 3
    ROUTINE = 4
    SELF_CARE = 5


class Allergy(BaseModel):
    allergen: str
    reaction: str


class Vitals(BaseModel):
    bp: Optional[str] = None
    hr: Optional[int] = None
    temp: Optional[float] = None
    bg: Optional[int] = None
    spo2: Optional[int] = None


class LabValue(BaseModel):
    test: str
    value: float
    unit: str


class PatientProfile(BaseModel):
    id: str
    age: int
    sex: str
    mode: AgentMode
    chief_complaint: str
    communication_style: CommunicationStyle
    medications: list[str] = Field(default_factory=list)
    allergies: list[Allergy] = Field(default_factory=list)
    medical_history: list[str] = Field(default_factory=list)
    family_history: list[str] = Field(default_factory=list)
    social: dict[str, str] = Field(default_factory=dict)
    vitals: Optional[Vitals] = None
    labs: Optional[list[LabValue]] = None
    opening_message: str
    expected_urgency: Optional[int] = None
    red_flags_present: list[str] = Field(default_factory=list)
    edge_case_tags: list[str] = Field(default_factory=list)


class ToolCall(BaseModel):
    tool: str
    input: dict
    output: dict


class ConversationTurn(BaseModel):
    role: str
    content: str


class Trace(BaseModel):
    profile_id: str
    mode: AgentMode
    turns: list[ConversationTurn] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    final_urgency: Optional[int] = None
    metadata: dict = Field(default_factory=dict)
