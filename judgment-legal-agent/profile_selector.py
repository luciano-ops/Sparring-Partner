"""Weighted profile selector — picks profiles to match target distributions.

Given slider percentages for legal_domain, client_sentiment, and interaction_type,
selects profiles from the classified pool that best approximate the targets across
all three dimensions simultaneously.

Uses a greedy scoring algorithm: for each slot, pick the profile that most reduces
the gap between current and target distributions.
"""

from __future__ import annotations

import random
from collections import defaultdict
from models import CaseProfile


def select_profiles(
    classified: dict,
    distributions: dict[str, dict[str, float]],
    total_count: int,
    seed: int | None = None,
) -> list[CaseProfile]:
    """Select profiles matching target distributions.

    Args:
        classified: Output from classify_all() — contains "profiles" list
        distributions: {
            "legal_domain": {"Contract & Commercial": 20, "IP & Technology": 30, ...},
            "client_sentiment": {"Frustrated": 25, ...},
            "interaction_type": {"Legal Consultation": 15, ...},
        }  (percentages, each group sums to 100)
        total_count: How many profiles to select
        seed: Optional random seed for reproducibility

    Returns:
        List of selected CaseProfile objects
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
                dim_targets[label] = total_count - allocated
            else:
                count = round(total_count * pct / total_pct)
                dim_targets[label] = count
                allocated += count
        targets[dim] = dim_targets

    # Build candidate pool with shuffled order
    pool = list(classified["profiles"])
    rng.shuffle(pool)

    selected: list[CaseProfile] = []
    selected_set: set[str] = set()

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

            score = 0.0
            for dim, dim_targets in targets.items():
                label = classification[dim]
                target_count = dim_targets.get(label, 0)
                current_count = current[dim][label]

                if target_count <= 0:
                    score -= 2.0
                elif current_count < target_count:
                    gap = (target_count - current_count) / target_count
                    score += gap
                else:
                    score -= 0.5

            if score > best_score:
                best_score = score
                best_indices = [idx]
            elif score == best_score:
                best_indices.append(idx)

        if not best_indices:
            break

        chosen_idx = rng.choice(best_indices)
        profile, classification = pool[chosen_idx]

        selected.append(profile)
        selected_set.add(profile.id)

        for dim in targets:
            label = classification[dim]
            current[dim][label] += 1

        pool.pop(chosen_idx)

    return selected


def get_achieved_distribution(
    profiles: list[CaseProfile],
    classified: dict,
) -> dict[str, dict[str, int]]:
    """Get the actual distribution of a list of selected profiles."""
    lookup = {p.id: c for p, c in classified["profiles"]}

    result: dict[str, dict[str, int]] = {
        "legal_domain": defaultdict(int),
        "client_sentiment": defaultdict(int),
        "interaction_type": defaultdict(int),
    }

    for p in profiles:
        c = lookup.get(p.id, {})
        for dim in result:
            label = c.get(dim, "Unknown")
            result[dim][label] += 1

    return {dim: dict(labels) for dim, labels in result.items()}
