"""Symptom lookup tool — matches reported symptoms against condition database."""

from __future__ import annotations

import json
from pathlib import Path

_DATA_PATH = Path(__file__).parent.parent / "data" / "conditions.json"
_CONDITIONS = None


def _load_conditions():
    global _CONDITIONS
    if _CONDITIONS is None:
        with open(_DATA_PATH) as f:
            _CONDITIONS = json.load(f)["conditions"]
    return _CONDITIONS


def _normalize(text: str) -> str:
    return text.lower().strip()


def _symptom_match_score(reported: list[str], condition: dict) -> float:
    """Score how well reported symptoms match a condition.

    Key symptoms are weighted 2x. Score is normalized by condition symptom count.
    """
    reported_lower = {_normalize(s) for s in reported}
    condition_symptoms = {_normalize(s) for s in condition["symptoms"]}
    key_symptoms = {_normalize(s) for s in condition["key_symptoms"]}

    regular_matches = 0
    key_matches = 0

    for rs in reported_lower:
        for cs in condition_symptoms:
            if rs in cs or cs in rs:
                if cs in key_symptoms:
                    key_matches += 1
                else:
                    regular_matches += 1
                break

    total_score = (regular_matches + key_matches * 2.0)
    max_possible = len(condition_symptoms) + len(key_symptoms)
    if max_possible == 0:
        return 0.0

    match_ratio = total_score / max_possible
    prevalence_boost = condition.get("prevalence", 0.5) * 0.2
    return match_ratio + prevalence_boost


def _check_demographics(condition: dict, age: int | None, sex: str | None) -> float:
    """Return a demographic multiplier (0.3 to 1.0)."""
    demo = condition.get("typical_demographics", {})
    multiplier = 1.0

    if age is not None:
        age_min = demo.get("age_min", 0)
        age_max = demo.get("age_max", 100)
        if age < age_min or age > age_max:
            multiplier *= 0.3
        high_risk_min = demo.get("high_risk_age_min")
        if high_risk_min and age >= high_risk_min:
            multiplier *= 1.2

    if sex is not None:
        pred = demo.get("sex_predilection")
        if pred and pred != sex.lower():
            multiplier *= 0.6

    return min(multiplier, 1.0)


def _find_matching_red_flags(reported: list[str], condition: dict) -> list[str]:
    """Check if any reported symptoms match this condition's red flags."""
    if not condition.get("red_flags"):
        return []
    if "all symptoms are red flags" in condition["red_flags"]:
        return reported

    reported_lower = {_normalize(s) for s in reported}
    flags = []
    for rf in condition["red_flags"]:
        rf_lower = _normalize(rf)
        for rs in reported_lower:
            if rs in rf_lower or rf_lower in rs:
                flags.append(rf)
                break
    return flags


def symptom_lookup(
    symptoms: list[str],
    duration: str | None = None,
    severity: str | None = None,
    patient_age: int | None = None,
    patient_sex: str | None = None,
) -> dict:
    """Look up possible conditions based on reported symptoms."""
    conditions = _load_conditions()
    scored = []

    for condition in conditions:
        base_score = _symptom_match_score(symptoms, condition)
        if base_score < 0.1:
            continue

        demo_multiplier = _check_demographics(condition, patient_age, patient_sex)
        final_score = base_score * demo_multiplier

        if severity == "severe":
            final_score *= 1.1
        if duration and any(w in duration.lower() for w in ["week", "month", "year"]):
            # Chronic presentations slightly favor chronic conditions
            if condition["category"] in ("endocrine", "mental_health", "musculoskeletal"):
                final_score *= 1.1

        red_flags = _find_matching_red_flags(symptoms, condition)

        scored.append({
            "condition": condition["name"],
            "category": condition["category"],
            "match_score": round(final_score, 3),
            "matched_key_symptoms": [
                s for s in condition["key_symptoms"]
                if any(_normalize(r) in _normalize(s) or _normalize(s) in _normalize(r) for r in symptoms)
            ],
            "red_flags_triggered": red_flags,
            "urgency_range": condition["urgency_range"],
        })

    scored.sort(key=lambda x: x["match_score"], reverse=True)
    top_results = scored[:5]

    any_red_flags = any(r["red_flags_triggered"] for r in top_results)

    return {
        "possible_conditions": top_results,
        "red_flags_detected": any_red_flags,
        "all_red_flags": [
            flag
            for r in top_results
            for flag in r["red_flags_triggered"]
        ],
        "note": "These are possibilities to discuss with a healthcare provider, not diagnoses.",
    }
