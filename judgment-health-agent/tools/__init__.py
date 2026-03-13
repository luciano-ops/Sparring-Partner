"""Tool definitions and dispatch for the health agent."""

import functools
from .symptom_db import symptom_lookup
from .lab_interpreter import interpret_labs
from .drug_checker import drug_interaction_check
from .triage import classify_urgency
from .intake import generate_intake_summary
from .risk_calculator import calculate_risk_score
from .guidelines import check_guidelines
from .medication_info import lookup_medication_info
from .preventive_care import check_preventive_care
from .care_plan import generate_care_plan
from instrumentation import tracer


def _traced_tool(name: str, fn):
    """Wrap a tool function with its own named Judgment span.

    Each tool call appears as a separate span in the Judgment dashboard
    (e.g., 'symptom_lookup', 'check_guidelines') with full input/output capture.
    """
    @tracer.observe(span_name=name, span_type="tool")
    @functools.wraps(fn)
    def wrapper(**kwargs):
        return fn(**kwargs)
    return wrapper


TOOL_DEFINITIONS = [
    {
        "name": "symptom_lookup",
        "description": "Look up possible conditions based on reported symptoms. Returns a ranked differential diagnosis list with likelihood indicators. Use this whenever a patient describes symptoms that need assessment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symptoms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of symptoms the patient has reported"
                },
                "duration": {
                    "type": "string",
                    "description": "How long symptoms have been present (e.g., '3 days', '2 weeks')"
                },
                "severity": {
                    "type": "string",
                    "enum": ["mild", "moderate", "severe"],
                    "description": "Overall severity of symptoms"
                },
                "patient_age": {
                    "type": "integer",
                    "description": "Patient's age in years"
                },
                "patient_sex": {
                    "type": "string",
                    "enum": ["male", "female"],
                    "description": "Patient's biological sex"
                }
            },
            "required": ["symptoms"]
        }
    },
    {
        "name": "interpret_labs",
        "description": "Interpret laboratory test results. Compares values against reference ranges, flags abnormalities, and identifies clinically meaningful patterns. Use this whenever a patient provides lab values.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lab_values": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "test": {"type": "string", "description": "Test name (e.g., 'Hemoglobin', 'TSH', 'Glucose')"},
                            "value": {"type": "number", "description": "The numeric result"},
                            "unit": {"type": "string", "description": "Unit of measurement"}
                        },
                        "required": ["test", "value"]
                    },
                    "description": "Array of lab test results"
                },
                "patient_age": {
                    "type": "integer",
                    "description": "Patient's age for age-adjusted ranges"
                },
                "patient_sex": {
                    "type": "string",
                    "enum": ["male", "female"],
                    "description": "Patient's sex for sex-adjusted ranges"
                }
            },
            "required": ["lab_values"]
        }
    },
    {
        "name": "drug_interaction_check",
        "description": "Check for known drug interactions between medications. Use this whenever a patient reports taking ANY medications, even a single one — check it against common OTC drugs and supplements.",
        "input_schema": {
            "type": "object",
            "properties": {
                "medications": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of medication names the patient is taking (e.g., 'lisinopril', 'metformin', 'ibuprofen')"
                }
            },
            "required": ["medications"]
        }
    },
    {
        "name": "classify_urgency",
        "description": "Classify the urgency level of a patient's presentation based on their symptoms and risk factors. Returns a level from 1 (EMERGENCY) to 5 (SELF-CARE) with rationale. Use this in EVERY mode — triage, intake, and lab review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symptoms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of symptoms"
                },
                "red_flags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Any red flag symptoms identified"
                },
                "patient_age": {
                    "type": "integer",
                    "description": "Patient's age"
                },
                "medical_history": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Relevant medical history"
                },
                "vital_signs": {
                    "type": "object",
                    "description": "Any vital signs provided (bp, hr, temp, spo2)",
                    "properties": {
                        "bp": {"type": "string"},
                        "hr": {"type": "integer"},
                        "temp": {"type": "number"},
                        "spo2": {"type": "integer"}
                    }
                }
            },
            "required": ["symptoms"]
        }
    },
    {
        "name": "generate_intake_summary",
        "description": "Generate a structured patient intake summary from collected information. Use this at the end of a patient intake conversation to produce a formatted summary document.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chief_complaint": {"type": "string", "description": "Primary reason for visit in patient's words"},
                "onset_duration": {"type": "string", "description": "When symptoms started and how long they've lasted"},
                "medications": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Current medications with doses"
                },
                "allergies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "allergen": {"type": "string"},
                            "reaction": {"type": "string"}
                        }
                    },
                    "description": "Known allergies and reaction types"
                },
                "medical_history": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Chronic conditions, surgeries, hospitalizations"
                },
                "family_history": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Relevant family medical history"
                },
                "social_history": {
                    "type": "object",
                    "description": "Tobacco, alcohol, substance use",
                    "properties": {
                        "tobacco": {"type": "string"},
                        "alcohol": {"type": "string"},
                        "other": {"type": "string"}
                    }
                },
                "vitals": {
                    "type": "object",
                    "description": "Any vital signs provided",
                    "properties": {
                        "bp": {"type": "string"},
                        "hr": {"type": "integer"},
                        "temp": {"type": "number"},
                        "bg": {"type": "integer"}
                    }
                },
                "additional_notes": {"type": "string", "description": "Any other relevant information gathered"}
            },
            "required": ["chief_complaint"]
        }
    },
    # ── NEW TOOLS ──
    {
        "name": "calculate_risk_score",
        "description": "Calculate a validated clinical risk score. Supports HEART score (chest pain), Wells score (DVT/PE risk), and PHQ-9 (depression severity). Use this whenever a clinical risk score is applicable — chest pain patients MUST get a HEART score, patients with DVT/PE symptoms MUST get Wells, depressed patients MUST get PHQ-9.",
        "input_schema": {
            "type": "object",
            "properties": {
                "score_type": {
                    "type": "string",
                    "enum": ["heart_score", "wells_score", "phq9"],
                    "description": "Which risk score to calculate"
                },
                "symptoms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patient's symptoms"
                },
                "patient_age": {
                    "type": "integer",
                    "description": "Patient's age"
                },
                "risk_factors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Known risk factors (e.g., 'hypertension', 'diabetes', 'smoking', 'obesity', 'family history of heart disease')"
                }
            },
            "required": ["score_type", "symptoms"]
        }
    },
    {
        "name": "check_guidelines",
        "description": "Look up evidence-based clinical practice guidelines for a condition. Returns screening recommendations, treatment protocols, lifestyle modifications, and monitoring schedules from major medical organizations (AHA, ADA, USPSTF, etc.). Use this for ANY condition that has established guidelines — hypertension, diabetes, depression, chest pain, headache, back pain, UTI.",
        "input_schema": {
            "type": "object",
            "properties": {
                "condition": {
                    "type": "string",
                    "description": "The condition to look up guidelines for (e.g., 'hypertension', 'diabetes', 'depression', 'chest_pain')"
                },
                "patient_age": {
                    "type": "integer",
                    "description": "Patient's age for age-specific recommendations"
                },
                "comorbidities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patient's other conditions that may affect treatment"
                }
            },
            "required": ["condition"]
        }
    },
    {
        "name": "lookup_medication_info",
        "description": "Look up detailed information about a specific medication including class, side effects, contraindications, monitoring requirements, and food interactions. Use this for EVERY medication the patient is taking — patients want to understand what they're on.",
        "input_schema": {
            "type": "object",
            "properties": {
                "medication_name": {
                    "type": "string",
                    "description": "Name of the medication (e.g., 'lisinopril', 'metformin 500mg daily')"
                }
            },
            "required": ["medication_name"]
        }
    },
    {
        "name": "check_preventive_care",
        "description": "Check which preventive care screenings, immunizations, and health maintenance items are recommended for a patient based on their age, sex, and risk factors. ALWAYS use this during intake visits and wellness checks. Also use during triage/lab review to identify overdue screenings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_age": {
                    "type": "integer",
                    "description": "Patient's age"
                },
                "patient_sex": {
                    "type": "string",
                    "enum": ["male", "female"],
                    "description": "Patient's sex"
                },
                "medical_history": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Known conditions and risk factors"
                },
                "last_screenings": {
                    "type": "object",
                    "description": "Any known dates of last screenings (e.g., {'mammogram': '2023', 'colonoscopy': '2020'})"
                }
            },
            "required": ["patient_age", "patient_sex"]
        }
    },
    {
        "name": "generate_care_plan",
        "description": "Generate a structured care plan with follow-up timeline, self-care recommendations, medication instructions, warning signs, and questions for the next visit. ALWAYS use this at the end of EVERY conversation to give the patient a clear action plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "diagnosis_or_concern": {
                    "type": "string",
                    "description": "Primary diagnosis or health concern being addressed"
                },
                "urgency_level": {
                    "type": "integer",
                    "description": "Urgency level (1-5) from classify_urgency"
                },
                "medications": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patient's current medications"
                },
                "follow_up_needed": {
                    "type": "boolean",
                    "description": "Whether follow-up is recommended"
                },
                "patient_age": {
                    "type": "integer",
                    "description": "Patient's age"
                },
                "special_instructions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Any condition-specific instructions"
                }
            },
            "required": ["diagnosis_or_concern"]
        }
    },
]

_RAW_TOOLS = {
    "symptom_lookup": symptom_lookup,
    "interpret_labs": interpret_labs,
    "drug_interaction_check": drug_interaction_check,
    "classify_urgency": classify_urgency,
    "generate_intake_summary": generate_intake_summary,
    "calculate_risk_score": calculate_risk_score,
    "check_guidelines": check_guidelines,
    "lookup_medication_info": lookup_medication_info,
    "check_preventive_care": check_preventive_care,
    "generate_care_plan": generate_care_plan,
}

# Each tool gets its own named span in Judgment
TOOL_MAP = {name: _traced_tool(name, fn) for name, fn in _RAW_TOOLS.items()}


def execute_tool(name: str, input_data: dict) -> dict:
    """Execute a tool by name and return the result.

    Individual tool tracing is handled by _traced_tool wrappers above —
    each tool appears as its own named span (e.g., 'symptom_lookup') in Judgment.
    """
    handler = TOOL_MAP.get(name)
    if not handler:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = handler(**input_data)
        return result
    except Exception as e:
        return {"error": f"Tool execution failed: {str(e)}"}
