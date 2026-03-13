"""Care plan generator — produces structured follow-up and care plans."""

from __future__ import annotations

import random
from datetime import datetime


def generate_care_plan(
    diagnosis_or_concern: str,
    urgency_level: int | None = None,
    medications: list[str] | None = None,
    follow_up_needed: bool = True,
    patient_age: int | None = None,
    special_instructions: list[str] | None = None,
) -> dict:
    """Generate a structured care plan with follow-up recommendations."""
    medications = medications or []
    special_instructions = special_instructions or []
    urgency_level = urgency_level or 4

    # Follow-up timeline based on urgency
    follow_up_map = {
        1: {"timeframe": "Immediate", "setting": "Emergency department", "interval": "As directed by ER physician"},
        2: {"timeframe": "Within 24 hours", "setting": "Urgent care or same-day appointment", "interval": "Follow up within 1 week"},
        3: {"timeframe": "Within 1-2 days", "setting": "Primary care or specialist", "interval": "Follow up in 1-2 weeks"},
        4: {"timeframe": "Within 1 week", "setting": "Primary care", "interval": "Follow up in 2-4 weeks"},
        5: {"timeframe": "As needed", "setting": "Primary care at next routine visit", "interval": "Follow up in 4-6 weeks or as needed"},
    }

    follow_up = follow_up_map.get(urgency_level, follow_up_map[4])

    # Self-care recommendations
    general_self_care = [
        "Stay well-hydrated (aim for 8 glasses of water daily)",
        "Get adequate rest (7-9 hours of sleep)",
        "Monitor symptoms and note any changes",
        "Keep a symptom diary with dates, severity, and triggers",
    ]

    # Medication adherence reminders
    med_instructions = []
    if medications:
        med_instructions.append("Continue all current medications as prescribed unless told otherwise by your provider")
        med_instructions.append("Do not start any new medications (including OTC) without consulting your provider")
        if len(medications) >= 3:
            med_instructions.append("Consider using a pill organizer to manage multiple medications")
        med_instructions.append("Report any new side effects to your healthcare provider promptly")

    # Warning signs (return precautions)
    warning_signs = [
        "Significant worsening of current symptoms",
        "New symptoms not previously discussed",
        "Fever above 101.3°F (38.5°C)",
        "Inability to take medications or keep fluids down",
    ]

    if urgency_level <= 2:
        warning_signs.extend([
            "Any difficulty breathing or chest pain",
            "Confusion or altered mental status",
            "Severe pain not controlled by recommended measures",
        ])

    # Questions to ask at follow-up
    follow_up_questions = [
        f"What are the next steps for evaluating my {diagnosis_or_concern}?",
        "Are there any additional tests I should have?",
        "Should I see a specialist?",
        "Are my current medications still appropriate?",
        "What lifestyle changes would you recommend?",
    ]

    # Age-specific additions
    age_notes = []
    if patient_age is not None:
        if patient_age >= 65:
            age_notes = [
                "Fall prevention: ensure home safety (grab bars, night lights, remove tripping hazards)",
                "Discuss advance directives if not already in place",
                "Review all medications with provider for polypharmacy concerns",
            ]
        elif patient_age < 18:
            age_notes = [
                "Ensure a parent or guardian is aware of the care plan",
                "Monitor for any impact on school attendance or activities",
            ]

    plan = {
        "care_plan_for": diagnosis_or_concern,
        "generated_date": datetime.now().strftime("%Y-%m-%d"),
        "urgency_level": urgency_level,
        "follow_up": {
            "recommended_timeframe": follow_up["timeframe"],
            "recommended_setting": follow_up["setting"],
            "follow_up_interval": follow_up["interval"],
            "follow_up_needed": follow_up_needed,
        },
        "self_care_recommendations": general_self_care,
        "medication_instructions": med_instructions if med_instructions else ["No current medications to manage"],
        "warning_signs_seek_immediate_care": warning_signs,
        "questions_for_next_visit": follow_up_questions,
        "special_instructions": special_instructions if special_instructions else ["None at this time"],
    }

    if age_notes:
        plan["age_specific_recommendations"] = age_notes

    return plan
