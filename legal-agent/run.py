"""CLI runner for the legal research agent."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from models import (
    QueryProfile,
    LegalResearchType,
    Complexity,
    TimeSensitivity,
    RequesterPersona,
    DepthPreference,
)
from agent import LegalResearchAgent
from tracing import flush_and_shutdown


def generate_random_profile() -> QueryProfile:
    """Generate a random legal research profile for testing."""
    import random

    return QueryProfile(
        research_type=random.choice(list(LegalResearchType)),
        domain=random.choice([
            "Contract Law", "Intellectual Property", "Corporate/M&A",
            "Employment Law", "Regulatory Compliance", "Litigation/Dispute Resolution",
        ]),
        complexity=random.choice(list(Complexity)),
        query=random.choice([
            "Analyze the enforceability of non-compete agreements for remote workers across state lines",
            "Research fiduciary duty standards for corporate directors in derivative actions",
            "Compare trade secret protection frameworks under DTSA vs state UTSA adoptions",
            "Evaluate regulatory compliance requirements for AI systems under the EU AI Act",
            "Research the legal framework for cross-border M&A due diligence requirements",
            "Analyze recent developments in securities fraud class action standing requirements",
        ]),
        time_sensitivity=random.choice(list(TimeSensitivity)),
        requester_persona=random.choice(list(RequesterPersona)),
        depth_preference=random.choice(list(DepthPreference)),
    )


def run_single(profile: QueryProfile, verbose: bool = False) -> dict:
    """Run a single legal research session."""
    agent = LegalResearchAgent(profile=profile, verbose=verbose)
    trace = agent.run_session()

    return {
        "profile_id": trace.profile_id,
        "turns": len(trace.turns),
        "tool_calls": len(trace.tool_calls),
        "tokens": trace.total_tokens,
        "duration": trace.duration,
        "report_length": len(trace.final_report) if trace.final_report else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Run legal research agent")
    parser.add_argument("--count", type=int, default=1, help="Number of sessions")
    parser.add_argument("--concurrency", type=int, default=1, help="Parallel sessions")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--profile", type=str, help="JSON profile override")
    args = parser.parse_args()

    profiles = []
    for _ in range(args.count):
        if args.profile:
            profiles.append(QueryProfile(**json.loads(args.profile)))
        else:
            profiles.append(generate_random_profile())

    results = []
    if args.concurrency <= 1:
        for p in profiles:
            results.append(run_single(p, verbose=args.verbose))
    else:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {executor.submit(run_single, p, args.verbose): p for p in profiles}
            for future in as_completed(futures):
                results.append(future.result())

    flush_and_shutdown()

    print(f"\n{'='*60}")
    print(f"Completed {len(results)} sessions")
    for r in results:
        print(f"  {r['profile_id']}: {r['turns']} turns, {r['tokens']:,} tokens, {r['duration']:.0f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
