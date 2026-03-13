"""Classify patient profiles along the three Judgment dashboard dimensions.

Each of the 1050 pre-generated profiles gets tagged with:
  - clinical_domain:   Cardiac, Endocrine, General/Preventive, GI, Mental Health,
                       Musculoskeletal, Neurological, Respiratory
  - patient_sentiment: Frustrated, Anxious, Reassured, Still Anxious
  - interaction_type:  Emergency Escalation, History Collection, Lab Interpretation,
                       Medication Review, Preventive Screening, Symptom Assessment,
                       Patient Education

Classification is deterministic and cached after first call.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from models import PatientProfile


# ── Clinical Domain rules (checked in priority order) ────────────────────────

_DOMAIN_RULES: list[tuple[str, list[str], list[str]]] = [
    # (domain_name, edge_case_tags to match, chief_complaint keywords)
    ("Cardiac", ["cardiac"], [
        "chest pain", "palpitation", "heart racing", "heart attack",
        "tachycardia", "crushing", "diaphoresis",
    ]),
    ("Neurological", ["neuro"], [
        "headache", "migraine", "seizure", "dizzy", "dizziness", "vertigo",
        "face drooping", "arm is weak", "numbness", "tingling", "tremor",
        "worst headache", "vision", "confusion", "balance",
    ]),
    ("Mental Health", ["mental_health"], [
        "depression", "anxiety", "suicidal", "panic", "mood",
    ]),
    ("Endocrine", [], [
        "diabetes", "thyroid", "blood sugar", "glucose", "hba1c", "insulin",
    ]),
    ("Respiratory", [], [
        "cough", "breathing", "asthma", "pneumonia", "shortness of breath",
        "wheezing", "respiratory",
    ]),
    ("Musculoskeletal", [], [
        "back pain", "knee pain", "joint pain", "sciatica", "ankle",
        "sprain", "arthritis", "shoulder", "neck pain",
    ]),
    ("GI", [], [
        "heartburn", "bloating", "diarrhea", "nausea", "vomiting",
        "abdominal pain", "stomach", "liver", "appendicitis", "constipation",
        "right side", "acid reflux",
    ]),
]

_PREVENTIVE_KEYWORDS = [
    "annual", "wellness", "preventive", "new patient", "transferring care",
    "physical exam",
]


def classify_domain(profile: PatientProfile) -> str:
    """Classify a profile into a clinical domain."""
    tags = set(profile.edge_case_tags)
    complaint = profile.chief_complaint.lower()

    # Check tag-based and keyword-based rules
    for domain, tag_matches, keywords in _DOMAIN_RULES:
        if any(t in tags for t in tag_matches):
            return domain
        if any(kw in complaint for kw in keywords):
            return domain

    # Check lab-based domains
    if profile.labs:
        lab_tests = {l.test.lower() for l in profile.labs}
        if any(t in lab_tests for t in ["tsh", "free t4", "t3"]):
            return "Endocrine"
        if any(t in lab_tests for t in ["hba1c", "fasting glucose"]):
            return "Endocrine"
        if any(t in lab_tests for t in ["alt", "ast", "bilirubin"]):
            return "GI"
        if any(t in lab_tests for t in ["bun", "creatinine"]):
            return "General / Preventive"

    # General/Preventive
    if profile.mode.value == "intake":
        if any(kw in complaint for kw in _PREVENTIVE_KEYWORDS):
            return "General / Preventive"

    return "General / Preventive"


# ── Patient Sentiment (mirrors patient_simulator.py logic exactly) ───────────

def classify_sentiment(profile: PatientProfile) -> str:
    """Classify sentiment from deterministic MD5 hash of profile ID."""
    arc_seed = int(hashlib.md5(profile.id.encode()).hexdigest(), 16) % 100
    if arc_seed < 25:
        return "Frustrated"
    elif arc_seed < 50:
        return "Anxious"
    elif arc_seed < 75:
        return "Reassured"
    else:
        return "Still Anxious"


# ── Interaction Type ─────────────────────────────────────────────────────────

_MEDICATION_KEYWORDS = [
    "refill", "medication", "side effect", "dosage", "prescription",
    "taking", "medicine", "drug", "pill",
]


def classify_interaction(profile: PatientProfile) -> str:
    """Classify expected interaction type from profile fields."""
    mode = profile.mode.value
    complaint = profile.chief_complaint.lower()

    # Emergency escalation: triage with high urgency
    if mode == "triage" and profile.expected_urgency in (1, 2):
        return "Emergency Escalation"

    # Lab interpretation
    if mode == "lab_review":
        return "Lab Interpretation"

    # Medication review: has active meds AND complaint mentions medication topics
    if profile.medications and any(kw in complaint for kw in _MEDICATION_KEYWORDS):
        return "Medication Review"

    # Preventive screening
    if mode == "intake" and any(kw in complaint for kw in _PREVENTIVE_KEYWORDS):
        return "Preventive Screening"

    # History collection (non-preventive intake)
    if mode == "intake":
        return "History Collection"

    # Symptom assessment (triage, non-emergency)
    if mode == "triage":
        return "Symptom Assessment"

    return "Patient Education"


# ── Full classification ──────────────────────────────────────────────────────

def classify_profile(profile: PatientProfile) -> dict[str, str]:
    """Classify a single profile along all 3 dimensions."""
    return {
        "clinical_domain": classify_domain(profile),
        "patient_sentiment": classify_sentiment(profile),
        "interaction_type": classify_interaction(profile),
    }


def classify_all(profiles: list[PatientProfile]) -> dict:
    """Classify all profiles and return an index structure.

    Returns:
        {
            "profiles": [(profile, classification_dict), ...],
            "counts": {
                "clinical_domain": {"Cardiac": 59, ...},
                "patient_sentiment": {"Frustrated": 248, ...},
                "interaction_type": {"Emergency Escalation": 180, ...},
            }
        }
    """
    classified = []
    counts: dict[str, dict[str, int]] = {
        "clinical_domain": defaultdict(int),
        "patient_sentiment": defaultdict(int),
        "interaction_type": defaultdict(int),
    }

    for p in profiles:
        c = classify_profile(p)
        classified.append((p, c))
        for dim, label in c.items():
            counts[dim][label] += 1

    # Convert defaultdicts to regular dicts for JSON serialization
    counts = {dim: dict(sorted(labels.items())) for dim, labels in counts.items()}

    return {"profiles": classified, "counts": counts}


# ── Quick test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from profiles.generator import load_profiles

    profiles_path = Path(__file__).parent / "profiles" / "patient_profiles.json"
    profiles = load_profiles(profiles_path)

    result = classify_all(profiles)
    print(f"Classified {len(result['profiles'])} profiles\n")

    for dim, labels in result["counts"].items():
        total = sum(labels.values())
        print(f"  {dim}:")
        for label, count in sorted(labels.items(), key=lambda x: -x[1]):
            pct = count / total * 100
            print(f"    {label:25s} {count:4d}  ({pct:5.1f}%)")
        print()
