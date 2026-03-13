"""CLI entrypoint for running deep research sessions."""

import argparse
import json
import os
import sys
import time

from tqdm import tqdm

from models import QueryProfile, ResearchTrace
from agent import ResearchAgent
from tracing import get_tracer, flush_and_shutdown


PROFILES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "profiles", "query_profiles.json"
)
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def load_profiles(path: str) -> list[QueryProfile]:
    """Load query profiles from JSON file."""
    with open(path) as f:
        data = json.load(f)
    return [QueryProfile(**item) for item in data]


def save_trace(trace: ResearchTrace, output_dir: str):
    """Save a research trace to JSON."""
    os.makedirs(output_dir, exist_ok=True)
    filename = f"trace_{trace.profile_id}.json"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w") as f:
        f.write(trace.model_dump_json(indent=2))
    return filepath


def run_session(profile: QueryProfile, verbose: bool = False) -> ResearchTrace:
    """Run a single research session."""
    agent = ResearchAgent(profile=profile, verbose=verbose)
    return agent.run_session()


def main():
    parser = argparse.ArgumentParser(
        description="Deep Research Agent - Run research sessions"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of research sessions to run (default: 1)",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Run a specific profile by ID (e.g., query_0001)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output during research sessions",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of concurrent sessions (default: 1)",
    )
    parser.add_argument(
        "--profiles-path",
        type=str,
        default=PROFILES_PATH,
        help="Path to query profiles JSON file",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=OUTPUT_DIR,
        help="Directory to save output traces",
    )
    args = parser.parse_args()

    # Validate environment
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable is required")
        sys.exit(1)
    if not os.environ.get("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable is required")
        sys.exit(1)

    # Initialize tracing (no-op if JUDGMENT_API_KEY is unset or judgeval missing)
    tracer = get_tracer()
    tracing_status = "enabled" if tracer else "disabled"

    # Load profiles
    try:
        profiles = load_profiles(args.profiles_path)
    except FileNotFoundError:
        print(f"Error: Profiles not found at {args.profiles_path}")
        print("Run `python3.11 profiles/generator.py` to generate profiles first.")
        sys.exit(1)

    if not profiles:
        print("Error: No profiles found. Run the generator first.")
        sys.exit(1)

    # Select profiles to run
    if args.profile:
        selected = [p for p in profiles if p.id == args.profile]
        if not selected:
            print(f"Error: Profile '{args.profile}' not found.")
            print(f"Available profiles: {', '.join(p.id for p in profiles[:10])}...")
            sys.exit(1)
    else:
        selected = profiles[: args.count]

    print(f"\nDeep Research Agent")
    print(f"{'='*40}")
    print(f"Sessions to run: {len(selected)}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Tracing: {tracing_status}")
    print(f"Output: {args.output_dir}")
    print(f"{'='*40}\n")

    traces: list[ResearchTrace] = []
    total_tokens = 0
    total_duration = 0.0

    if args.concurrency <= 1:
        # Sequential execution with progress bar
        for profile in tqdm(selected, desc="Research sessions", disable=args.verbose):
            try:
                trace = run_session(profile, verbose=args.verbose)
                traces.append(trace)

                filepath = save_trace(trace, args.output_dir)
                total_tokens += trace.total_tokens
                total_duration += trace.duration

                if not args.verbose:
                    tqdm.write(
                        f"  Completed: {profile.id} | "
                        f"{len(trace.turns)} turns, "
                        f"{len(trace.tool_calls)} tool calls, "
                        f"{trace.total_tokens:,} tokens, "
                        f"{trace.duration:.1f}s"
                    )
            except Exception as e:
                tqdm.write(f"  Error on {profile.id}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
    else:
        # Concurrent execution
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {
                executor.submit(run_session, p, args.verbose): p for p in selected
            }
            with tqdm(total=len(selected), desc="Research sessions") as pbar:
                for future in as_completed(futures):
                    profile = futures[future]
                    try:
                        trace = future.result()
                        traces.append(trace)

                        filepath = save_trace(trace, args.output_dir)
                        total_tokens += trace.total_tokens
                        total_duration += trace.duration

                        tqdm.write(
                            f"  Completed: {profile.id} | "
                            f"{len(trace.turns)} turns, "
                            f"{len(trace.tool_calls)} tool calls, "
                            f"{trace.total_tokens:,} tokens, "
                            f"{trace.duration:.1f}s"
                        )
                    except Exception as e:
                        tqdm.write(f"  Error on {profile.id}: {e}")
                    pbar.update(1)

    # Flush traces before printing summary so they're guaranteed exported
    if tracer:
        print("\nFlushing traces to Judgment Labs...")
        flush_and_shutdown()

    # Summary
    print(f"\n{'='*40}")
    print(f"Summary")
    print(f"{'='*40}")
    print(f"Sessions completed: {len(traces)}/{len(selected)}")
    print(f"Total tokens: {total_tokens:,}")
    print(f"Total duration: {total_duration:.1f}s")
    if traces:
        avg_turns = sum(len(t.turns) for t in traces) / len(traces)
        avg_tools = sum(len(t.tool_calls) for t in traces) / len(traces)
        print(f"Avg turns/session: {avg_turns:.1f}")
        print(f"Avg tool calls/session: {avg_tools:.1f}")
    print(f"Output saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
