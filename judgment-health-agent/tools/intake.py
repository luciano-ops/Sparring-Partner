"""Intake summary generator — formats collected patient data into structured output."""

from __future__ import annotations


def generate_intake_summary(
    chief_complaint: str,
    onset_duration: str | None = None,
    medications: list[str] | None = None,
    allergies: list[dict] | None = None,
    medical_history: list[str] | None = None,
    family_history: list[str] | None = None,
    social_history: dict | None = None,
    vitals: dict | None = None,
    additional_notes: str | None = None,
) -> dict:
    """Generate a structured patient intake summary."""
    summary_lines = [
        "PATIENT INTAKE SUMMARY",
        "=" * 40,
        f"Chief Complaint: {chief_complaint}",
    ]

    if onset_duration:
        summary_lines.append(f"Onset/Duration: {onset_duration}")

    summary_lines.append("")

    # Medications
    summary_lines.append("MEDICATIONS:")
    if medications:
        for med in medications:
            summary_lines.append(f"  - {med}")
    else:
        summary_lines.append("  - None reported")

    summary_lines.append("")

    # Allergies
    summary_lines.append("ALLERGIES:")
    if allergies:
        for allergy in allergies:
            allergen = allergy.get("allergen", "Unknown")
            reaction = allergy.get("reaction", "Unknown reaction")
            summary_lines.append(f"  - {allergen} -> {reaction}")
    else:
        summary_lines.append("  - NKDA (No Known Drug Allergies)")

    summary_lines.append("")

    # Medical History
    summary_lines.append("MEDICAL HISTORY:")
    if medical_history:
        for condition in medical_history:
            summary_lines.append(f"  - {condition}")
    else:
        summary_lines.append("  - None reported")

    summary_lines.append("")

    # Family History
    summary_lines.append("FAMILY HISTORY:")
    if family_history:
        for item in family_history:
            summary_lines.append(f"  - {item}")
    else:
        summary_lines.append("  - None reported / Non-contributory")

    summary_lines.append("")

    # Vitals
    if vitals:
        summary_lines.append("VITALS:")
        if vitals.get("bp"):
            summary_lines.append(f"  BP: {vitals['bp']}")
        if vitals.get("hr"):
            summary_lines.append(f"  HR: {vitals['hr']} bpm")
        if vitals.get("temp"):
            summary_lines.append(f"  Temp: {vitals['temp']}°F")
        if vitals.get("bg"):
            summary_lines.append(f"  Blood Glucose: {vitals['bg']} mg/dL")
        summary_lines.append("")

    # Social History
    if social_history:
        summary_lines.append("SOCIAL HISTORY:")
        summary_lines.append(f"  Tobacco: {social_history.get('tobacco', 'Not assessed')}")
        summary_lines.append(f"  Alcohol: {social_history.get('alcohol', 'Not assessed')}")
        if social_history.get("other"):
            summary_lines.append(f"  Other: {social_history['other']}")
        summary_lines.append("")

    # Additional Notes
    if additional_notes:
        summary_lines.append("ADDITIONAL NOTES:")
        summary_lines.append(f"  {additional_notes}")
        summary_lines.append("")

    # Pre-visit recommendations
    summary_lines.append("PRE-VISIT RECOMMENDATIONS:")
    summary_lines.append("  - Bring current medication bottles or an updated medication list")
    summary_lines.append("  - Write down any questions you'd like to ask your doctor")
    if medications and len(medications) > 3:
        summary_lines.append("  - Consider requesting a medication reconciliation given your current medication list")
    if vitals and vitals.get("bp"):
        summary_lines.append("  - Continue monitoring blood pressure at home and bring your log")

    formatted_summary = "\n".join(summary_lines)

    # Structured data for downstream use
    structured = {
        "chief_complaint": chief_complaint,
        "onset_duration": onset_duration,
        "medications_count": len(medications) if medications else 0,
        "allergies_count": len(allergies) if allergies else 0,
        "has_medical_history": bool(medical_history),
        "has_vitals": bool(vitals),
        "has_social_history": bool(social_history),
        "completeness_score": _calc_completeness(
            chief_complaint, onset_duration, medications, allergies,
            medical_history, family_history, social_history, vitals,
        ),
    }

    return {
        "formatted_summary": formatted_summary,
        "structured_data": structured,
        "note": "Summary generated for pre-visit preparation. To be reviewed by clinical staff.",
    }


def _calc_completeness(
    chief_complaint, onset_duration, medications, allergies,
    medical_history, family_history, social_history, vitals,
) -> float:
    """Calculate how complete the intake is (0.0 to 1.0)."""
    fields = [
        bool(chief_complaint),
        bool(onset_duration),
        medications is not None,
        allergies is not None,
        bool(medical_history),
        bool(family_history),
        bool(social_history),
        bool(vitals),
    ]
    return round(sum(fields) / len(fields), 2)
