"""Urgency classification tool — rule-based triage scoring."""

from __future__ import annotations


# Emergency keywords that immediately trigger Level 1
_EMERGENCY_KEYWORDS = {
    "chest pain", "crushing chest", "chest pressure",
    "difficulty breathing", "can't breathe", "severe shortness of breath",
    "facial drooping", "arm weakness", "speech difficulty", "slurred speech",
    "worst headache of life", "thunderclap headache",
    "suicidal ideation with plan", "active suicidal thoughts",
    "uncontrolled bleeding", "severe hemorrhage",
    "loss of consciousness", "passed out", "syncope",
    "throat swelling", "anaphylaxis", "can't swallow",
    "seizure", "convulsion",
    "severe allergic reaction",
    "altered mental status", "confusion with fever",
}

# Urgent keywords that push toward Level 2
_URGENT_KEYWORDS = {
    "high fever", "fever over 103", "fever over 104",
    "chest tightness", "palpitations with dizziness",
    "severe abdominal pain", "rigid abdomen",
    "vomiting blood", "bloody stool", "black tarry stool",
    "sudden vision loss", "sudden numbness",
    "suicidal thoughts", "self-harm",
    "unable to keep fluids down",
    "severe dehydration",
    "head injury with vomiting",
    "first seizure",
}

# Age-based risk multipliers
_AGE_RISK = {
    (0, 3): 1.5,        # Neonates/infants — higher risk
    (3, 12): 1.2,       # Young children
    (12, 65): 1.0,      # Standard
    (65, 80): 1.2,      # Elderly
    (80, 150): 1.4,     # Very elderly
}


def _get_age_multiplier(age: int | None) -> float:
    if age is None:
        return 1.0
    for (lo, hi), mult in _AGE_RISK.items():
        if lo <= age < hi:
            return mult
    return 1.0


def _check_vital_urgency(vitals: dict | None) -> tuple[int, list[str]]:
    """Check vitals for concerning values. Returns (urgency_score, reasons)."""
    if not vitals:
        return 0, []

    score = 0
    reasons = []

    # Blood pressure
    bp = vitals.get("bp")
    if bp and "/" in str(bp):
        try:
            systolic, diastolic = map(int, str(bp).split("/"))
            if systolic >= 180 or diastolic >= 120:
                score += 3
                reasons.append(f"Severely elevated blood pressure ({bp})")
            elif systolic >= 160 or diastolic >= 100:
                score += 1
                reasons.append(f"Elevated blood pressure ({bp})")
        except ValueError:
            pass

    # Heart rate
    hr = vitals.get("hr")
    if hr is not None:
        if hr > 150 or hr < 40:
            score += 3
            reasons.append(f"Heart rate critically abnormal ({hr} bpm)")
        elif hr > 120 or hr < 50:
            score += 1
            reasons.append(f"Heart rate abnormal ({hr} bpm)")

    # Temperature
    temp = vitals.get("temp")
    if temp is not None:
        if temp >= 104.0:
            score += 3
            reasons.append(f"High fever ({temp}°F)")
        elif temp >= 102.0:
            score += 1
            reasons.append(f"Fever ({temp}°F)")

    # SpO2
    spo2 = vitals.get("spo2")
    if spo2 is not None:
        if spo2 < 90:
            score += 3
            reasons.append(f"Critically low oxygen ({spo2}%)")
        elif spo2 < 94:
            score += 1
            reasons.append(f"Low oxygen saturation ({spo2}%)")

    return score, reasons


def classify_urgency(
    symptoms: list[str],
    red_flags: list[str] | None = None,
    patient_age: int | None = None,
    medical_history: list[str] | None = None,
    vital_signs: dict | None = None,
) -> dict:
    """Classify urgency from 1 (EMERGENCY) to 5 (SELF-CARE)."""
    red_flags = red_flags or []
    medical_history = medical_history or []

    all_text = " ".join(symptoms + red_flags).lower()
    reasons = []

    # Check for emergency keywords
    for keyword in _EMERGENCY_KEYWORDS:
        if keyword in all_text:
            return {
                "urgency_level": 1,
                "label": "EMERGENCY",
                "rationale": f"Emergency presentation detected: {keyword}",
                "recommended_action": "Call 911 or go to the nearest emergency room immediately.",
                "timeframe": "Immediate",
                "contributing_factors": [f"Emergency symptom: {keyword}"],
            }

    # Score accumulation
    score = 0.0

    # Urgent keywords
    for keyword in _URGENT_KEYWORDS:
        if keyword in all_text:
            score += 2.0
            reasons.append(f"Urgent symptom: {keyword}")

    # Red flags
    if red_flags:
        score += len(red_flags) * 1.5
        reasons.extend([f"Red flag: {rf}" for rf in red_flags])

    # Vital signs
    vital_score, vital_reasons = _check_vital_urgency(vital_signs)
    score += vital_score
    reasons.extend(vital_reasons)

    # Age multiplier
    age_mult = _get_age_multiplier(patient_age)
    if age_mult > 1.0 and patient_age is not None:
        score *= age_mult
        reasons.append(f"Age-related risk adjustment (age {patient_age})")

    # Medical history risk factors
    high_risk_conditions = {
        "diabetes", "heart disease", "heart failure", "copd", "immunocompromised",
        "cancer", "kidney disease", "liver disease", "hiv", "transplant",
    }
    for condition in medical_history:
        if any(hrc in condition.lower() for hrc in high_risk_conditions):
            score += 0.5
            reasons.append(f"Risk factor: {condition}")

    # Map score to urgency level
    if score >= 5.0:
        level = 2
        label = "URGENT"
        action = "See a doctor today — visit urgent care or request a same-day appointment."
        timeframe = "Within hours"
    elif score >= 3.0:
        level = 3
        label = "SEMI-URGENT"
        action = "Schedule an appointment within 1-2 days. Monitor for worsening symptoms."
        timeframe = "24-48 hours"
    elif score >= 1.0:
        level = 4
        label = "ROUTINE"
        action = "Schedule an appointment at your convenience. Self-care measures may help in the meantime."
        timeframe = "Days to 1 week"
    else:
        level = 5
        label = "SELF-CARE"
        action = "This is likely manageable at home. See a doctor if symptoms persist or worsen."
        timeframe = "As needed"

    return {
        "urgency_level": level,
        "label": label,
        "rationale": f"Based on {len(symptoms)} symptoms, {len(red_flags)} red flags, and clinical risk assessment.",
        "recommended_action": action,
        "timeframe": timeframe,
        "contributing_factors": reasons if reasons else ["No high-risk features identified"],
        "score_detail": round(score, 2),
    }
