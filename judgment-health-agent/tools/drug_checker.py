"""Drug interaction checker — looks up known interactions between medications."""

from __future__ import annotations

import json
from pathlib import Path

_DATA_PATH = Path(__file__).parent.parent / "data" / "interactions.json"
_INTERACTIONS = None


def _load_interactions():
    global _INTERACTIONS
    if _INTERACTIONS is None:
        with open(_DATA_PATH) as f:
            _INTERACTIONS = json.load(f)["interactions"]
    return _INTERACTIONS


def _normalize_med(name: str) -> str:
    """Normalize medication name for matching.

    Strips dose info, lowercases, and extracts the drug name.
    E.g., 'Lisinopril 10mg daily' -> 'lisinopril'
    """
    name = name.lower().strip()
    # Strip common dose patterns
    parts = name.split()
    cleaned = []
    for part in parts:
        # Skip parts that look like doses or frequencies
        if any(unit in part for unit in ["mg", "ml", "mcg", "iu", "unit"]):
            continue
        if part in ("daily", "twice", "once", "bid", "tid", "qid", "prn", "qd", "qhs", "weekly", "monthly"):
            continue
        cleaned.append(part)
    return " ".join(cleaned) if cleaned else name.split()[0]


def _check_pair(med_a: str, med_b: str, interactions: list) -> dict | None:
    """Check if two medications have a known interaction."""
    a = _normalize_med(med_a)
    b = _normalize_med(med_b)

    for interaction in interactions:
        # Check primary pair
        ia = interaction["drug_a"].lower()
        ib = interaction["drug_b"].lower()

        if (a in ia or ia in a) and (b in ib or ib in b):
            return interaction
        if (b in ia or ia in b) and (a in ib or ib in a):
            return interaction

        # Check alternate matches
        for alt_a, alt_b in interaction.get("also_matches", []):
            alt_a = alt_a.lower()
            alt_b = alt_b.lower()
            if (a in alt_a or alt_a in a) and (b in alt_b or alt_b in b):
                return interaction
            if (b in alt_a or alt_a in b) and (a in alt_b or alt_b in a):
                return interaction

    return None


def drug_interaction_check(medications: list[str]) -> dict:
    """Check for interactions between a list of medications."""
    interactions_db = _load_interactions()
    found_interactions = []
    checked_pairs = set()

    for i, med_a in enumerate(medications):
        for med_b in medications[i + 1:]:
            pair_key = tuple(sorted([_normalize_med(med_a), _normalize_med(med_b)]))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)

            interaction = _check_pair(med_a, med_b, interactions_db)
            if interaction:
                found_interactions.append({
                    "between": [med_a, med_b],
                    "severity": interaction["severity"],
                    "mechanism": interaction["mechanism"],
                    "effect": interaction["effect"],
                    "recommendation": interaction["recommendation"],
                })

    # Sort by severity
    severity_order = {"major": 0, "moderate": 1, "minor": 2}
    found_interactions.sort(key=lambda x: severity_order.get(x["severity"], 3))

    has_major = any(i["severity"] == "major" for i in found_interactions)

    return {
        "interactions_found": found_interactions,
        "total_interactions": len(found_interactions),
        "has_major_interaction": has_major,
        "medications_checked": medications,
        "pairs_checked": len(checked_pairs),
        "note": "Always consult your pharmacist or prescriber about drug interactions. This check covers common interactions but is not exhaustive.",
    }
