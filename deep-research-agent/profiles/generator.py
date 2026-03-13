"""Generate diverse research query profiles using Claude."""

import json
import os
import sys

import anthropic

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import QueryProfile, ResearchType, Complexity, TimeSensitivity, RequesterPersona, DepthPreference

client = anthropic.Anthropic()
MODEL = "claude-haiku-4-20250514"

DOMAINS = [
    "AI/ML",
    "Biotech",
    "Climate",
    "Finance",
    "Geopolitics",
    "Healthcare",
    "Legal",
    "Education",
    "Cybersecurity",
    "Energy",
]

EDGE_CASE_TAGS = [
    "contradictory_sources",
    "rapidly_evolving",
    "misinformation_heavy",
    "sparse_data",
    "highly_technical",
    "politically_charged",
    "ethically_complex",
    "interdisciplinary",
]


def generate_batch(
    research_type: str,
    domain: str,
    count: int = 4,
) -> list[dict]:
    """Generate a batch of query profiles using Claude."""
    prompt = f"""Generate {count} diverse research query profiles for:
- Research type: {research_type}
- Domain: {domain}

Return a JSON array of {count} objects, each with these exact fields:
- "research_type": "{research_type}"
- "domain": "{domain}"
- "complexity": one of "Simple", "Moderate", "Complex", "Expert_Level" (vary across the batch)
- "query": string (a specific, realistic research question — NOT generic. Include real concepts, companies, technologies, etc.)
- "sub_questions": array of 3-5 follow-up questions the requester might ask
- "expected_sources": integer 3-12 (higher for more complex queries)
- "time_sensitivity": one of "Historical", "Current", "Breaking", "Evergreen" (vary across the batch)
- "requester_persona": one of "Executive", "Academic", "Journalist", "Student", "Analyst", "Curious_Generalist" (vary across the batch)
- "depth_preference": one of "Overview", "Detailed", "Exhaustive" (vary across the batch)
- "edge_case_tags": array of 0-3 tags from: "contradictory_sources", "rapidly_evolving", "misinformation_heavy", "sparse_data", "highly_technical", "politically_charged", "ethically_complex", "interdisciplinary"

Make each query specific and realistic. Avoid generic questions. Use real-world topics, technologies, companies, and events.
Return ONLY the JSON array."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text
    try:
        # Try direct parse
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try extracting from code block
        import re
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
        else:
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
            else:
                print(f"  Warning: Could not parse batch for {research_type}/{domain}")
                return []

    return data


def generate_all_profiles(target_count: int = 200) -> list[QueryProfile]:
    """Generate a full set of diverse profiles."""
    research_types = [rt.value for rt in ResearchType]
    profiles = []
    batch_num = 0
    total_batches = len(research_types) * len(DOMAINS)

    print(f"Generating ~{target_count} profiles across {len(research_types)} types x {len(DOMAINS)} domains...")

    profiles_per_batch = max(2, target_count // total_batches + 1)

    for rt in research_types:
        for domain in DOMAINS:
            batch_num += 1
            print(f"  Batch {batch_num}/{total_batches}: {rt} / {domain} ({profiles_per_batch} profiles)...")

            try:
                batch_data = generate_batch(rt, domain, count=profiles_per_batch)
                for item in batch_data:
                    try:
                        profile = QueryProfile(**item)
                        profiles.append(profile)
                    except Exception as e:
                        print(f"    Warning: Skipped invalid profile: {e}")
            except Exception as e:
                print(f"    Error generating batch: {e}")

            if len(profiles) >= target_count:
                break
        if len(profiles) >= target_count:
            break

    print(f"\nGenerated {len(profiles)} profiles total.")
    return profiles


def save_profiles(profiles: list[QueryProfile], path: str):
    """Save profiles to JSON file."""
    data = [p.model_dump() for p in profiles]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(profiles)} profiles to {path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate research query profiles")
    parser.add_argument("--count", type=int, default=200, help="Target number of profiles to generate")
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "query_profiles.json"),
        help="Output file path",
    )
    args = parser.parse_args()

    profiles = generate_all_profiles(target_count=args.count)
    save_profiles(profiles, args.output)


if __name__ == "__main__":
    main()
