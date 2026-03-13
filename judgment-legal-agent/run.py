"""Runner — executes the legal agent across case profiles and saves traces.

Usage:
    python3.11 run.py                        # Run 5 conversations (quick test)
    python3.11 run.py --count 100            # Run 100 conversations
    python3.11 run.py --profile case_0042    # Run a single specific profile
    python3.11 run.py --verbose              # Print full conversations
    python3.11 run.py --generate-only        # Just generate profiles, don't run agent
"""

import argparse
import json
import random
import shutil
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from instrumentation import tracer
from models import CaseProfile, Complexity
from agent import LegalAgent
from client_simulator import ClientSimulator

OUTPUT_DIR = Path(__file__).parent / "output"
PROFILES_PATH = Path(__file__).parent / "profiles" / "case_profiles.json"


class ProgressBar:
    """Live terminal progress bar with ETA and per-trace stats."""

    BLOCK_FULL = "\u2588"
    BLOCK_EMPTY = "\u2591"

    def __init__(self, total: int):
        self.total = total
        self.completed = 0
        self.failed = 0
        self.start_time = time.time()
        self.tool_calls = 0
        self.turns = 0
        self._term_width = shutil.get_terminal_size((80, 24)).columns

    def _format_time(self, seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s:02d}s"

    def _render(self):
        elapsed = time.time() - self.start_time
        done = self.completed + self.failed
        pct = done / self.total if self.total else 0

        if done > 0 and done < self.total:
            eta = (elapsed / done) * (self.total - done)
            time_str = f"{self._format_time(elapsed)}<{self._format_time(eta)}"
        else:
            time_str = self._format_time(elapsed)

        avg_tools = self.tool_calls / self.completed if self.completed else 0
        avg_turns = self.turns / self.completed if self.completed else 0
        stats = f"tools/conv={avg_tools:.1f}  turns/conv={avg_turns:.1f}"

        label = f"  {done}/{self.total} "
        suffix = f" {pct:>5.1%}  {time_str}  {stats}"
        bar_space = self._term_width - len(label) - len(suffix) - 2
        bar_space = max(bar_space, 10)
        filled = int(bar_space * pct)
        bar = self.BLOCK_FULL * filled + self.BLOCK_EMPTY * (bar_space - filled)

        line = f"\r{label}{bar}{suffix}"
        line = line[: self._term_width]
        sys.stdout.write(f"\r{' ' * self._term_width}\r")
        sys.stdout.write(line)
        sys.stdout.flush()

    def update(self, profile_id: str, tool_count: int = 0, turn_count: int = 0):
        self.completed += 1
        self.tool_calls += tool_count
        self.turns += turn_count
        self._render()

    def fail(self, profile_id: str):
        self.failed += 1
        self._render()

    def finish(self):
        sys.stdout.write("\n")
        sys.stdout.flush()


def _pick_max_turns(profile: CaseProfile) -> int:
    """Pick turn count based on case complexity.

    Routine cases resolve faster; High_Stakes cases need more turns.
    This avoids wasting tokens on long conversations for simple cases.
    """
    if profile.complexity == Complexity.Routine:
        return random.choice([4, 4, 5])
    elif profile.complexity == Complexity.Moderate:
        return random.choice([5, 6, 6])
    elif profile.complexity == Complexity.Complex:
        return random.choice([6, 7, 8])
    else:  # High_Stakes
        return random.choice([7, 8, 9, 10])


@tracer.observe(span_type="function")
def run_conversation(
    profile: CaseProfile,
    max_turns: int = 0,
    model: str = "claude-sonnet-4-20250514",
    verbose: bool = False,
    session_id: str = "",
) -> dict:
    """Run a full multi-turn legal consultation for one case profile.

    The agent talks to a Gemini-powered client simulator. Returns the trace.
    Each call creates one trace in Judgment with full conversation + tool spans.
    """
    if max_turns <= 0:
        max_turns = _pick_max_turns(profile)

    # Set Judgment trace metadata
    if session_id:
        tracer.set_session_id(session_id)
    tracer.set_customer_id(profile.id)
    tracer.set_attributes({
        "case.type": profile.case_type.value,
        "case.jurisdiction": profile.jurisdiction,
        "case.complexity": profile.complexity.value,
        "case.urgency": profile.urgency.value,
        "case.client_industry": profile.client_industry,
        "case.communication_style": profile.communication_style.value,
        "case.opposing_party": profile.opposing_party,
        "case.legal_issue": profile.legal_issue,
        "case.edge_case_tags": json.dumps(profile.edge_case_tags),
        "case.max_turns": max_turns,
    })

    agent = LegalAgent(model=model)
    agent.reset(profile)
    client = ClientSimulator(profile)

    # Start with client's opening message
    client_msg = client.get_opening_message()
    tracer.set_input(json.dumps({
        "profile_id": profile.id,
        "case_type": profile.case_type.value,
        "jurisdiction": profile.jurisdiction,
        "legal_issue": profile.legal_issue,
        "communication_style": profile.communication_style.value,
        "opening_message": client_msg,
    }))

    if verbose:
        print(f"\n{'='*60}")
        print(f"Profile: {profile.id[:8]} | Type: {profile.case_type.value} | {profile.jurisdiction}")
        print(f"Issue: {profile.legal_issue}")
        print(f"Style: {profile.communication_style.value} | Urgency: {profile.urgency.value}")
        print(f"{'='*60}")
        print(f"\n\033[94m[CLIENT]\033[0m {client_msg}\n")

    for turn in range(max_turns):
        # Agent responds
        agent_response = agent.run_turn(client_msg)

        if verbose:
            # Show tool calls
            if agent.turns and agent.turns[-1].tool_calls:
                for tc in agent.turns[-1].tool_calls:
                    print(f"  \033[33m[TOOL: {tc.tool_name}]\033[0m {json.dumps(tc.tool_input)[:120]}...")
            print(f"\n\033[92m[AGENT]\033[0m {agent_response[:300]}{'...' if len(agent_response) > 300 else ''}\n")

        # Check if agent is wrapping up
        if agent.is_wrapping_up(agent_response):
            if verbose:
                print("  >> Agent wrapping up, ending consultation.")
            break

        # If not the last allowed turn, get client response
        if turn < max_turns - 1:
            client_msg = client.respond(agent_response)
            if verbose:
                print(f"\033[94m[CLIENT]\033[0m {client_msg}\n")

    # Build trace result
    metadata = agent.get_metadata()
    metadata["profile"] = profile.model_dump(mode="json")
    metadata["edge_case_tags"] = profile.edge_case_tags

    # Build conversation transcript for Judgment classifiers
    transcript_lines = []
    for t in agent.turns:
        label = "CLIENT" if t.role == "client" else "AGENT"
        transcript_lines.append(f"[{label}]: {t.content}")
    transcript = "\n\n".join(transcript_lines)

    # Set trace output for Judgment — includes both stats and full dialogue
    tracer.set_output(json.dumps({
        "total_turns": metadata.get("total_turns"),
        "tools_used": metadata.get("tools_used"),
        "total_tool_calls": metadata.get("total_tool_calls"),
        "conversation_transcript": transcript,
    }))

    return {
        "profile_id": profile.id,
        "case_type": profile.case_type.value,
        "jurisdiction": profile.jurisdiction,
        "complexity": profile.complexity.value,
        "turns": [t.model_dump() for t in agent.turns],
        "tool_calls": [tc.model_dump() for tc in agent.tool_calls],
        "metadata": metadata,
    }


def _assign_session_ids(profiles: list[CaseProfile]) -> list[str]:
    """Assign session IDs: 70% standalone (no session), 30% grouped in clusters of 2-4.

    Returns a list of session IDs parallel to profiles. Empty string = no session.
    """
    n = len(profiles)
    session_ids = [""] * n
    indices = list(range(n))
    random.shuffle(indices)

    session_count = int(n * 0.30)
    i = 0
    while i < session_count:
        cluster_size = min(random.choice([2, 2, 3, 4]), session_count - i)
        if cluster_size < 2:
            break
        sid = str(uuid.uuid4())
        for j in range(cluster_size):
            session_ids[indices[i + j]] = sid
        i += cluster_size

    return session_ids


def run_batch(
    profiles: list[CaseProfile],
    max_turns: int = 0,
    model: str = "claude-sonnet-4-20250514",
    concurrency: int = 1,
    verbose: bool = False,
    progress_callback=None,
) -> list[dict]:
    """Run consultations for a batch of profiles.

    Uses thread pool for concurrent execution when concurrency > 1.
    70% of traces are standalone, 30% are grouped into sessions of 2-4.

    Args:
        progress_callback: Optional callable that receives progress event dicts.
                          Used by panel.py for SSE streaming to the web UI.
    """
    session_ids = _assign_session_ids(profiles)
    session_count = sum(1 for s in session_ids if s)
    unique_sessions = len(set(s for s in session_ids if s))

    traces = []
    failed = []
    total = len(profiles)

    print(f"\n  Judgment Legal Agent Runner")
    print(f"  {'─'*36}")
    print(f"  Conversations : {total}")
    print(f"  Model         : {model}")
    print(f"  Concurrency   : {concurrency}")
    print(f"  Sessions      : {unique_sessions} sessions ({session_count} traces), {total - session_count} standalone")
    print(f"  Output        : {OUTPUT_DIR}\n")

    bar = ProgressBar(total)
    bar._render()
    start_time = time.time()

    def _emit_progress(profile_id, tool_count=0, turn_count=0, error=None):
        """Emit progress to both terminal bar and optional web callback."""
        elapsed = time.time() - start_time
        completed = len(traces)
        failed_count = len(failed)

        avg_tools = sum(t["metadata"].get("total_tool_calls", 0) for t in traces) / max(completed, 1)
        avg_turns = sum(t["metadata"].get("total_turns", 0) for t in traces) / max(completed, 1)

        if progress_callback:
            progress_callback({
                "type": "error" if error else "progress",
                "completed": completed,
                "failed": failed_count,
                "total": total,
                "profile_id": profile_id,
                "tool_count": tool_count,
                "turn_count": turn_count,
                "avg_tools": avg_tools,
                "avg_turns": avg_turns,
                "elapsed": elapsed,
                "error": error,
            })

    if concurrency <= 1:
        # Sequential
        for i, profile in enumerate(profiles):
            try:
                sid = session_ids[i]
                trace = run_conversation(profile, max_turns, model, verbose, sid)
                traces.append(trace)
                tool_count = trace["metadata"]["total_tool_calls"]
                turns = trace["metadata"]["total_turns"]
                if not verbose:
                    bar.update(profile.id, tool_count, turns)
                _emit_progress(profile.id, tool_count, turns)
            except Exception as e:
                if not verbose:
                    bar.fail(profile.id)
                failed.append({"profile_id": profile.id, "error": str(e)})
                _emit_progress(profile.id, error=str(e))
                if verbose:
                    import traceback
                    traceback.print_exc()
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_profile = {
                executor.submit(run_conversation, p, max_turns, model, verbose, session_ids[i]): p
                for i, p in enumerate(profiles)
            }
            for future in as_completed(future_to_profile):
                profile = future_to_profile[future]
                try:
                    trace = future.result()
                    traces.append(trace)
                    tool_count = trace["metadata"]["total_tool_calls"]
                    turns = trace["metadata"]["total_turns"]
                    if not verbose:
                        bar.update(profile.id, tool_count, turns)
                    _emit_progress(profile.id, tool_count, turns)
                except Exception as e:
                    if not verbose:
                        bar.fail(profile.id)
                    failed.append({"profile_id": profile.id, "error": str(e)})
                    _emit_progress(profile.id, error=str(e))

    if not verbose:
        bar.finish()
    elapsed = time.time() - start_time

    print(f"\n  {'═'*36}")
    print(f"  ✓ Completed : {len(traces)}/{total}")
    if failed:
        print(f"  ✗ Failed    : {len(failed)}")
    print(f"  ⏱ Time      : {elapsed:.1f}s ({elapsed/max(len(traces),1):.1f}s avg)")

    if traces:
        total_tokens = sum(
            t["metadata"].get("total_input_tokens", 0) + t["metadata"].get("total_output_tokens", 0)
            for t in traces
        )
        total_tools = sum(t["metadata"].get("total_tool_calls", 0) for t in traces)
        avg_turns = sum(t["metadata"].get("total_turns", 0) for t in traces) / len(traces)
        print(f"  📊 Tokens    : {total_tokens:,}")
        print(f"  🔧 Tools     : {total_tools} ({total_tools/len(traces):.1f}/conv)")
        print(f"  💬 Turns     : {avg_turns:.1f} avg")

    print(f"  {'═'*36}")

    return traces


def load_profiles(path: Path) -> list[CaseProfile]:
    """Load case profiles from JSON file."""
    data = json.loads(path.read_text())
    return [CaseProfile(**p) for p in data]


def main():
    parser = argparse.ArgumentParser(description="Judgment Legal Agent Runner")
    parser.add_argument("--count", type=int, default=5, help="Number of conversations to run (default: 5)")
    parser.add_argument("--profile", type=str, help="Run a single profile by ID or index (e.g., case_0042)")
    parser.add_argument("--generate-only", action="store_true", help="Generate profiles without running agent")
    parser.add_argument("--max-turns", type=int, default=0, help="Max turns per conversation (0 = auto-vary)")
    parser.add_argument("--model", type=str, default="claude-sonnet-4-20250514", help="Claude model to use")
    parser.add_argument("--concurrency", type=int, default=1, help="Concurrent conversations (default: 1)")
    parser.add_argument("--verbose", action="store_true", help="Print conversation details")
    args = parser.parse_args()

    import os
    # Check for required API keys
    missing = []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if not os.environ.get("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")
    if not os.environ.get("JUDGMENT_API_KEY"):
        missing.append("JUDGMENT_API_KEY")
    if not os.environ.get("JUDGMENT_ORG_ID"):
        missing.append("JUDGMENT_ORG_ID")
    if missing:
        print(f"Error: Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)

    # Generate or load profiles
    if not PROFILES_PATH.exists() or args.generate_only:
        print(f"Generating {max(args.count, 210)} case profiles...")
        from profiles.generator import generate_all_profiles
        profiles_data = generate_all_profiles(max(args.count, 210))
        PROFILES_PATH.write_text(json.dumps(profiles_data, indent=2, default=str))
        print(f"Saved to {PROFILES_PATH}")
        if args.generate_only:
            return

    profiles = load_profiles(PROFILES_PATH)
    print(f"Loaded {len(profiles)} profiles from {PROFILES_PATH}")

    # Filter if specific profile requested
    if args.profile:
        if args.profile.startswith("case_"):
            try:
                idx = int(args.profile.split("_")[1])
                if 0 <= idx < len(profiles):
                    profiles = [profiles[idx]]
                else:
                    print(f"Error: Index {idx} out of range (0-{len(profiles)-1})")
                    sys.exit(1)
            except ValueError:
                profiles = [p for p in profiles if p.id.startswith(args.profile)]
        else:
            profiles = [p for p in profiles if p.id.startswith(args.profile)]

        if not profiles:
            print(f"Profile '{args.profile}' not found.")
            return
        args.count = len(profiles)

    # Select subset
    profiles = profiles[: args.count]

    # Run
    traces = run_batch(
        profiles,
        max_turns=args.max_turns,
        model=args.model,
        concurrency=args.concurrency,
        verbose=args.verbose,
    )

    # Save traces
    if traces:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        trace_file = OUTPUT_DIR / f"traces_{timestamp}.json"
        trace_file.write_text(json.dumps(traces, indent=2, default=str))
        print(f"\nTraces saved to: {trace_file}")

        summary = {
            "run_timestamp": timestamp,
            "total_conversations": len(traces),
            "model": args.model,
            "case_type_distribution": {},
            "avg_turns": 0,
            "avg_tool_calls": 0,
            "total_tokens": 0,
        }
        for t in traces:
            ct = t.get("case_type", "unknown")
            summary["case_type_distribution"][ct] = summary["case_type_distribution"].get(ct, 0) + 1
        summary["avg_turns"] = round(sum(t["metadata"]["total_turns"] for t in traces) / len(traces), 1)
        summary["avg_tool_calls"] = round(sum(t["metadata"]["total_tool_calls"] for t in traces) / len(traces), 1)
        summary["total_tokens"] = sum(
            t["metadata"].get("total_input_tokens", 0) + t["metadata"].get("total_output_tokens", 0)
            for t in traces
        )

        summary_file = OUTPUT_DIR / f"summary_{timestamp}.json"
        summary_file.write_text(json.dumps(summary, indent=2))
        print(f"Summary saved to: {summary_file}")

    # Flush all traces to Judgment before exiting
    print("\nFlushing traces to Judgment...")
    tracer.shutdown(timeout_millis=30000)
    print("Done. Check your Judgment dashboard: https://app.judgmentlabs.ai")


if __name__ == "__main__":
    main()
