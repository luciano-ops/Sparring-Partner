"""Weighted profile selector — picks profiles to match target distributions.

Given slider percentages for clinical_domain, patient_sentiment, and interaction_type,
selects profiles from the classified pool that best approximate the targets across
all three dimensions simultaneously.

Uses a greedy scoring algorithm: for each slot, pick the profile that most reduces
the gap between current and target distributions.
"""

from __future__ import annotations

import random
from collections import defaultdict
from models import PatientProfile
from profile_classifier import classify_all


def select_profiles(
    classified: dict,
    distributions: dict[str, dict[str, float]],
    total_count: int,
    seed: int | None = None,
) -> list[PatientProfile]:
    """Select profiles matching target distributions.

    Args:
        classified: Output from classify_all() — contains "profiles" list
        distributions: {
            "clinical_domain": {"Cardiac": 20, "Neurological": 30, ...},
            "patient_sentiment": {"Frustrated": 25, ...},
            "interaction_type": {"Emergency Escalation": 15, ...},
        }  (percentages, each group sums to 100)
        total_count: How many profiles to select
        seed: Optional random seed for reproducibility

    Returns:
        List of selected PatientProfile objects
    """
    rng = random.Random(seed)

    # Convert percentages to target counts
    targets: dict[str, dict[str, int]] = {}
    for dim, labels in distributions.items():
        total_pct = sum(labels.values())
        if total_pct == 0:
            continue
        dim_targets = {}
        allocated = 0
        sorted_labels = sorted(labels.items(), key=lambda x: -x[1])
        for i, (label, pct) in enumerate(sorted_labels):
            if i == len(sorted_labels) - 1:
                # Last one gets the remainder to avoid rounding issues
                dim_targets[label] = total_count - allocated
            else:
                count = round(total_count * pct / total_pct)
                dim_targets[label] = count
                allocated += count
        targets[dim] = dim_targets

    # Build candidate pool with shuffled order
    pool = list(classified["profiles"])  # [(profile, classification_dict), ...]
    rng.shuffle(pool)

    selected: list[PatientProfile] = []
    selected_set: set[str] = set()  # track by profile ID to avoid duplicates

    # Running counts of what we've selected so far
    current: dict[str, dict[str, int]] = {
        dim: defaultdict(int) for dim in targets
    }

    for _ in range(total_count):
        if not pool:
            break

        best_score = -float("inf")
        best_indices: list[int] = []

        for idx, (profile, classification) in enumerate(pool):
            if profile.id in selected_set:
                continue

            # Score = sum of gap reductions across all dimensions
            score = 0.0
            for dim, dim_targets in targets.items():
                label = classification[dim]
                target_count = dim_targets.get(label, 0)
                current_count = current[dim][label]

                if target_count <= 0:
                    # We don't want any more of this label — penalize
                    score -= 2.0
                elif current_count < target_count:
                    # We need more of this label — reward proportionally to gap
                    gap = (target_count - current_count) / target_count
                    score += gap
                else:
                    # We already have enough — penalize slightly
                    score -= 0.5

            if score > best_score:
                best_score = score
                best_indices = [idx]
            elif score == best_score:
                best_indices.append(idx)

        if not best_indices:
            break

        # Random tiebreak among best
        chosen_idx = rng.choice(best_indices)
        profile, classification = pool[chosen_idx]

        selected.append(profile)
        selected_set.add(profile.id)

        # Update running counts
        for dim in targets:
            label = classification[dim]
            current[dim][label] += 1

        # Remove from pool
        pool.pop(chosen_idx)

    return selected


def get_achieved_distribution(
    profiles: list[PatientProfile],
    classified: dict,
) -> dict[str, dict[str, int]]:
    """Get the actual distribution of a list of selected profiles.

    Useful for showing the user what they'll actually get vs what they requested.
    """
    # Build a lookup from profile ID to classification
    lookup = {p.id: c for p, c in classified["profiles"]}

    result: dict[str, dict[str, int]] = {
        "clinical_domain": defaultdict(int),
        "patient_sentiment": defaultdict(int),
        "interaction_type": defaultdict(int),
    }

    for p in profiles:
        c = lookup.get(p.id, {})
        for dim in result:
            label = c.get(dim, "Unknown")
            result[dim][label] += 1

    return {dim: dict(labels) for dim, labels in result.items()}


# ── Quick test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from profiles.generator import load_profiles

    profiles_path = Path(__file__).parent / "profiles" / "patient_profiles.json"
    profiles = load_profiles(profiles_path)
    classified = classify_all(profiles)

    # Test: heavily weight Neurological + Frustrated
    dist = {
        "clinical_domain": {
            "Cardiac": 10, "Endocrine": 10, "General / Preventive": 10,
            "GI": 10, "Mental Health": 10, "Musculoskeletal": 10,
            "Neurological": 30, "Respiratory": 10,
        },
        "patient_sentiment": {
            "Frustrated": 40, "Anxious": 20, "Reassured": 20, "Still Anxious": 20,
        },
        "interaction_type": {
            "Emergency Escalation": 20, "History Collection": 15,
            "Lab Interpretation": 20, "Preventive Screening": 10,
            "Symptom Assessment": 35,
        },
    }

    selected = select_profiles(classified, dist, total_count=50, seed=42)
    achieved = get_achieved_distribution(selected, classified)

    print(f"Selected {len(selected)} profiles\n")
    for dim in achieved:
        print(f"  {dim}:")
        for label, count in sorted(achieved[dim].items(), key=lambda x: -x[1]):
            target_pct = dist[dim].get(label, 0)
            actual_pct = count / len(selected) * 100
            print(f"    {label:25s} {count:3d} ({actual_pct:5.1f}%)  target={target_pct}%")
        print()
