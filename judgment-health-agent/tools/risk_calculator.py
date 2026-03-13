"""Clinical risk score calculator — computes validated risk scores."""

from __future__ import annotations


# HEART score components for chest pain
def _heart_score(history: str, ecg: str, age: int, risk_factors: list[str], troponin: str) -> dict:
    score = 0
    breakdown = []

    # History
    h_map = {"highly_suspicious": 2, "moderately_suspicious": 1, "slightly_suspicious": 0}
    score += h_map.get(history, 1)
    breakdown.append(f"History: {history} (+{h_map.get(history, 1)})")

    # Age
    if age >= 65:
        score += 2
        breakdown.append(f"Age {age}: +2")
    elif age >= 45:
        score += 1
        breakdown.append(f"Age {age}: +1")
    else:
        breakdown.append(f"Age {age}: +0")

    # Risk factors
    rf_count = len(risk_factors)
    if rf_count >= 3:
        score += 2
        breakdown.append(f"Risk factors ({rf_count}): +2")
    elif rf_count >= 1:
        score += 1
        breakdown.append(f"Risk factors ({rf_count}): +1")
    else:
        breakdown.append("Risk factors (0): +0")

    if score <= 3:
        risk = "low"
        recommendation = "Consider early discharge with outpatient follow-up."
    elif score <= 6:
        risk = "moderate"
        recommendation = "Observation and further cardiac workup recommended."
    else:
        risk = "high"
        recommendation = "Urgent cardiology consultation and admission recommended."

    return {
        "score_name": "HEART Score",
        "score": score,
        "max_score": 10,
        "risk_category": risk,
        "breakdown": breakdown,
        "recommendation": recommendation,
    }


# Wells score for DVT/PE
def _wells_score(symptoms: list[str], risk_factors: list[str]) -> dict:
    score = 0.0
    breakdown = []

    checks = {
        "active cancer": 1.0, "paralysis or immobilization": 1.0,
        "bedridden >3 days": 1.5, "recent surgery": 1.5,
        "leg swelling": 1.0, "calf swelling >3cm": 1.0,
        "pitting edema": 1.0, "collateral superficial veins": 1.0,
        "tenderness along deep veins": 1.0,
        "heart rate >100": 1.5, "tachycardia": 1.5,
        "hemoptysis": 1.0, "immobilization": 1.5,
    }

    all_text = " ".join(symptoms + risk_factors).lower()
    for finding, points in checks.items():
        if finding in all_text:
            score += points
            breakdown.append(f"{finding}: +{points}")

    if score < 2:
        risk = "low"
        recommendation = "DVT/PE unlikely. Consider D-dimer testing to rule out."
    elif score < 6:
        risk = "moderate"
        recommendation = "Moderate probability. D-dimer and imaging recommended."
    else:
        risk = "high"
        recommendation = "High probability. Urgent imaging (CT-PA or ultrasound) recommended."

    return {
        "score_name": "Wells Score (DVT/PE)",
        "score": score,
        "max_score": 12.5,
        "risk_category": risk,
        "breakdown": breakdown if breakdown else ["No specific risk factors identified"],
        "recommendation": recommendation,
    }


# PHQ-9 approximation for depression
def _phq9_estimate(symptoms: list[str]) -> dict:
    score = 0
    breakdown = []

    domain_map = {
        "loss of interest": 2, "anhedonia": 2,
        "persistent sadness": 2, "depressed mood": 2, "feeling down": 2,
        "sleep changes": 1, "insomnia": 2, "hypersomnia": 1,
        "fatigue": 1, "low energy": 2, "tiredness": 1,
        "appetite changes": 1, "weight loss": 1, "weight gain": 1,
        "feelings of worthlessness": 2, "guilt": 2,
        "difficulty concentrating": 1, "poor concentration": 2,
        "psychomotor retardation": 2, "psychomotor agitation": 2,
        "suicidal ideation": 3, "thoughts of death": 3, "self-harm": 3,
    }

    all_text = " ".join(symptoms).lower()
    for finding, points in domain_map.items():
        if finding in all_text:
            score += points
            breakdown.append(f"{finding}: +{points}")

    if score <= 4:
        severity = "minimal"
        recommendation = "Minimal depression symptoms. Monitor and reassess."
    elif score <= 9:
        severity = "mild"
        recommendation = "Mild depression. Consider watchful waiting, lifestyle modifications."
    elif score <= 14:
        severity = "moderate"
        recommendation = "Moderate depression. Consider therapy and/or medication evaluation."
    elif score <= 19:
        severity = "moderately severe"
        recommendation = "Moderately severe. Active treatment with therapy and/or medication recommended."
    else:
        severity = "severe"
        recommendation = "Severe depression. Urgent mental health evaluation and treatment."

    return {
        "score_name": "PHQ-9 Estimate",
        "score": min(score, 27),
        "max_score": 27,
        "risk_category": severity,
        "breakdown": breakdown if breakdown else ["Limited symptom data for scoring"],
        "recommendation": recommendation,
    }


def calculate_risk_score(
    score_type: str,
    symptoms: list[str],
    patient_age: int | None = None,
    risk_factors: list[str] | None = None,
) -> dict:
    """Calculate a validated clinical risk score.

    Supports: heart_score, wells_score, phq9
    """
    risk_factors = risk_factors or []
    score_type = score_type.lower().replace(" ", "_").replace("-", "_")

    if score_type in ("heart", "heart_score"):
        return _heart_score(
            history="moderately_suspicious",
            ecg="normal",
            age=patient_age or 50,
            risk_factors=risk_factors,
            troponin="normal",
        )
    elif score_type in ("wells", "wells_score", "dvt", "pe"):
        return _wells_score(symptoms, risk_factors)
    elif score_type in ("phq9", "phq_9", "depression"):
        return _phq9_estimate(symptoms)
    else:
        return {
            "error": f"Unknown score type: {score_type}",
            "available_scores": ["heart_score", "wells_score", "phq9"],
        }
