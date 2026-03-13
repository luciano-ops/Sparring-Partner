"""Generate diverse case profiles using Claude."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic

from models import CaseProfile, CaseType

_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
MODEL = "claude-haiku-4-5-20251001"

JURISDICTIONS = [
    "California",
    "New York",
    "Texas",
    "Delaware",
    "Illinois",
    "Florida",
    "Massachusetts",
    "Washington",
    "Federal - 9th Circuit",
    "Federal - 2nd Circuit",
    "Federal - 5th Circuit",
    "Federal - D.C. Circuit",
]

INDUSTRIES = [
    "Tech",
    "Healthcare",
    "Finance",
    "Real Estate",
    "Manufacturing",
    "Energy",
    "Retail",
    "Pharmaceutical",
    "Media & Entertainment",
    "Aerospace & Defense",
]

EDGE_CASE_POOL = [
    "conflicting_clauses",
    "multi_jurisdiction",
    "statute_of_limitations_near",
    "ethical_conflict",
    "privileged_information",
    "conflicting_precedents",
    "regulatory_change_pending",
    "cross_border",
    "whistleblower",
    "class_action_potential",
    "force_majeure",
    "arbitration_clause",
    "non_compete",
    "trade_secret",
    "fiduciary_duty",
]


def generate_batch(
    case_type: str,
    batch_size: int,
    existing_count: int,
) -> list[dict]:
    """Generate a batch of case profiles for a given case type."""
    prompt = f"""Generate exactly {batch_size} diverse legal case profiles for case type: {case_type}.

Each profile must be a JSON object with these exact fields:
- case_type: "{case_type}"
- jurisdiction: one of {json.dumps(JURISDICTIONS)}
- client_industry: one of {json.dumps(INDUSTRIES)}
- complexity: one of ["Routine", "Moderate", "Complex", "High_Stakes"]
- legal_issue: a specific, realistic legal problem (1-2 sentences)
- key_facts: array of 4-7 relevant facts the client knows
- documents: array of 1-3 documents, each with: title, doc_type (contract|filing|correspondence|statute), summary
- opposing_party: realistic company or person name
- communication_style: one of ["Executive_Brief", "Detail_Oriented", "Anxious", "Adversarial", "Cooperative"]
- urgency: one of ["Immediate", "This_Week", "Standard", "Advisory"]
- edge_case_tags: array of 0-3 tags from {json.dumps(EDGE_CASE_POOL)}

IMPORTANT:
- Make each profile UNIQUE with different combinations of jurisdiction, industry, complexity, and communication style
- Legal issues should be specific and realistic, not generic
- Key facts should tell a coherent story
- Documents should be relevant to the legal issue
- Vary the edge cases — include some profiles with no edge cases
- Return ONLY a JSON array of objects, no markdown fences or other text"""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text

    # Parse JSON
    try:
        profiles = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            profiles = json.loads(raw[start:end])
        else:
            raise ValueError(f"Could not parse response as JSON:\n{raw[:500]}")

    return profiles


def generate_all_profiles(target_count: int = 210) -> list[dict]:
    """Generate profiles across all case types."""
    case_types = [ct.value for ct in CaseType]
    per_type = target_count // len(case_types)
    remainder = target_count % len(case_types)

    all_profiles: list[dict] = []

    for i, ct in enumerate(case_types):
        batch_size = per_type + (1 if i < remainder else 0)
        print(f"  Generating {batch_size} profiles for {ct}...")

        # Generate in sub-batches of 12 to avoid token limits
        generated = 0
        while generated < batch_size:
            sub_batch = min(12, batch_size - generated)
            try:
                batch = generate_batch(ct, sub_batch, len(all_profiles))
                # Validate and add UUIDs
                for p in batch:
                    p["case_type"] = ct
                    try:
                        profile = CaseProfile(**p)
                        all_profiles.append(profile.model_dump())
                    except Exception as e:
                        print(f"    Skipping invalid profile: {e}")
                generated += sub_batch
            except Exception as e:
                print(f"    Error generating batch: {e}")
                generated += sub_batch  # skip to avoid infinite loop

        print(f"    -> {len(all_profiles)} total profiles so far")

    return all_profiles


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 210
    output_path = os.path.join(os.path.dirname(__file__), "case_profiles.json")

    print(f"Generating {target} case profiles...")
    profiles = generate_all_profiles(target)

    with open(output_path, "w") as f:
        json.dump(profiles, f, indent=2, default=str)

    print(f"\nSaved {len(profiles)} profiles to {output_path}")

    # Print summary
    from collections import Counter

    types = Counter(p["case_type"] for p in profiles)
    jurisdictions = Counter(p["jurisdiction"] for p in profiles)
    complexities = Counter(p["complexity"] for p in profiles)

    print("\nDistribution:")
    print(f"  Case types: {dict(types)}")
    print(f"  Jurisdictions: {len(jurisdictions)} unique")
    print(f"  Complexities: {dict(complexities)}")


if __name__ == "__main__":
    main()
