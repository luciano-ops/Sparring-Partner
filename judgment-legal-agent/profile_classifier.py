"""Classify case profiles along the three Judgment dashboard dimensions.

Each of the 210 pre-generated profiles gets tagged with:
  - legal_domain:       Contract & Commercial, Employment & Labor, IP & Technology,
                        Regulatory & Compliance, Corporate & M&A, Litigation & Dispute
  - client_sentiment:   Frustrated, Anxious, Reassured, Skeptical
  - interaction_type:   Legal Consultation, Document Review, Risk Assessment,
                        Research Request, Compliance Check

Classification is deterministic and cached after first call.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from models import CaseProfile, CaseType, Urgency


# ── Legal Domain rules ────────────────────────────────────────────────────────

def classify_domain(profile: CaseProfile) -> str:
    """Classify a profile into a legal domain based on case_type and context."""
    ct = profile.case_type

    if ct == CaseType.Contract_Review:
        return "Contract & Commercial"
    elif ct == CaseType.Employment:
        return "Employment & Labor"
    elif ct == CaseType.IP_Dispute:
        return "IP & Technology"
    elif ct == CaseType.Regulatory_Compliance:
        return "Regulatory & Compliance"
    elif ct == CaseType.MandA_Due_Diligence:
        return "Corporate & M&A"
    elif ct == CaseType.Litigation:
        return "Litigation & Dispute"

    # Fallback: check legal_issue keywords
    issue = profile.legal_issue.lower()

    if any(kw in issue for kw in ["contract", "breach", "vendor", "clause", "agreement"]):
        return "Contract & Commercial"
    if any(kw in issue for kw in ["employ", "termination", "discriminat", "non-compete", "wage"]):
        return "Employment & Labor"
    if any(kw in issue for kw in ["patent", "trademark", "trade secret", "copyright", "ip "]):
        return "IP & Technology"
    if any(kw in issue for kw in ["compliance", "gdpr", "regulation", "sec ", "fda"]):
        return "Regulatory & Compliance"
    if any(kw in issue for kw in ["merger", "acquisition", "due diligence", "shareholder"]):
        return "Corporate & M&A"

    return "Litigation & Dispute"


# ── Client Sentiment (deterministic from MD5 hash of profile ID) ─────────────

def classify_sentiment(profile: CaseProfile) -> str:
    """Classify sentiment from deterministic MD5 hash — mirrors client_simulator.py arcs."""
    arc_seed = int(hashlib.md5(profile.id.encode()).hexdigest(), 16) % 100
    if arc_seed < 20:
        return "Anxious"
    elif arc_seed < 40:
        return "Confused"
    elif arc_seed < 60:
        return "Frustrated"
    elif arc_seed < 80:
        return "Neutral"
    else:
        return "Reassured"


# ── Interaction Type ─────────────────────────────────────────────────────────

_REVIEW_KEYWORDS = [
    "clause", "contract review", "nda", "license agreement", "terms",
    "indemnif", "limitation of liability", "assignment",
]

_RISK_KEYWORDS = [
    "exposure", "damages", "liable", "penalty", "fine", "settlement",
    "injunction", "cease and desist",
]


def classify_interaction(profile: CaseProfile) -> str:
    """Classify expected interaction type from profile fields."""
    ct = profile.case_type
    issue = profile.legal_issue.lower()

    # Compliance check: regulatory cases
    if ct == CaseType.Regulatory_Compliance:
        return "Compliance Check"

    # Document review: contract review cases with documents
    if ct == CaseType.Contract_Review:
        if profile.documents or any(kw in issue for kw in _REVIEW_KEYWORDS):
            return "Document Review"
        return "Legal Consultation"

    # M&A is always risk assessment (due diligence)
    if ct == CaseType.MandA_Due_Diligence:
        return "Risk Assessment"

    # Litigation: urgent = risk assessment, else consultation
    if ct == CaseType.Litigation:
        if profile.urgency in (Urgency.Immediate, Urgency.This_Week):
            return "Risk Assessment"
        if any(kw in issue for kw in _RISK_KEYWORDS):
            return "Risk Assessment"
        return "Legal Consultation"

    # IP: research-heavy
    if ct == CaseType.IP_Dispute:
        return "Research Request"

    # Employment: urgent = risk assessment, else consultation
    if ct == CaseType.Employment:
        if profile.urgency == Urgency.Immediate:
            return "Risk Assessment"
        return "Legal Consultation"

    return "Legal Consultation"


# ── Full classification ──────────────────────────────────────────────────────

def classify_profile(profile: CaseProfile) -> dict[str, str]:
    """Classify a single profile along all 3 dimensions."""
    return {
        "legal_domain": classify_domain(profile),
        "client_sentiment": classify_sentiment(profile),
        "interaction_type": classify_interaction(profile),
    }


def classify_all(profiles: list[CaseProfile]) -> dict:
    """Classify all profiles and return an index structure.

    Returns:
        {
            "profiles": [(profile, classification_dict), ...],
            "counts": {
                "legal_domain": {"Contract & Commercial": 35, ...},
                "client_sentiment": {"Frustrated": 52, ...},
                "interaction_type": {"Legal Consultation": 60, ...},
            }
        }
    """
    classified = []
    counts: dict[str, dict[str, int]] = {
        "legal_domain": defaultdict(int),
        "client_sentiment": defaultdict(int),
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

    profiles_path = Path(__file__).parent / "profiles" / "case_profiles.json"
    data = json.loads(profiles_path.read_text())
    profiles = [CaseProfile(**p) for p in data]

    result = classify_all(profiles)
    print(f"Classified {len(result['profiles'])} profiles\n")

    for dim, labels in result["counts"].items():
        total = sum(labels.values())
        print(f"  {dim}:")
        for label, count in sorted(labels.items(), key=lambda x: -x[1]):
            pct = count / total * 100
            print(f"    {label:25s} {count:4d}  ({pct:5.1f}%)")
        print()
