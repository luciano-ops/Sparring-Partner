"""Runner — executes the health agent across patient profiles and saves traces.

Usage:
    python run.py                        # Run 5 conversations (quick test)
    python run.py --count 100            # Run 100 conversations
    python run.py --count 1000           # Full batch
    python run.py --profile patient_0042 # Run a single specific profile
    python run.py --generate-only        # Just generate profiles, don't run agent
"""

import argparse
import json
import random
import shutil
import sys
import time
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from instrumentation import tracer
from models import AgentMode, PatientProfile
from agent import HealthAgent
from patient_simulator import PatientSimulator
from profiles.generator import generate_profiles, save_profiles, load_profiles


OUTPUT_DIR = Path(__file__).parent / "output"
PROFILES_PATH = Path(__file__).parent / "profiles" / "patient_profiles.json"


class ProgressBar:
    """Live terminal progress bar with ETA and per-trace stats."""

    BLOCK_FULL = "█"
    BLOCK_EMPTY = "░"

    def __init__(self, total: int):
        self.total = total
        self.completed = 0
        self.failed = 0
        self.start_time = time.time()
        self.tool_calls = 0
        self.turns = 0
        self._last_profile = ""
        self._term_width = shutil.get_terminal_size((80, 24)).columns

    def _format_time(self, seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s:02d}s"

    def _render(self, status_line: str = ""):
        """Redraw the progress bar in-place."""
        elapsed = time.time() - self.start_time
        done = self.completed + self.failed
        pct = done / self.total if self.total else 0

        # ETA
        if done > 0 and done < self.total:
            eta = (elapsed / done) * (self.total - done)
            time_str = f"{self._format_time(elapsed)}<{self._format_time(eta)}"
        else:
            time_str = self._format_time(elapsed)

        # Stats
        avg_tools = self.tool_calls / self.completed if self.completed else 0
        avg_turns = self.turns / self.completed if self.completed else 0
        stats = f"tools/conv={avg_tools:.1f}  turns/conv={avg_turns:.1f}"

        # Bar
        label = f"  {done}/{self.total} "
        suffix = f" {pct:>5.1%}  {time_str}  {stats}"
        bar_space = self._term_width - len(label) - len(suffix) - 2
        bar_space = max(bar_space, 10)
        filled = int(bar_space * pct)
        bar = self.BLOCK_FULL * filled + self.BLOCK_EMPTY * (bar_space - filled)

        line = f"\r{label}{bar}{suffix}"
        # Truncate if too wide
        line = line[:self._term_width]
        sys.stdout.write(f"\r{' ' * self._term_width}\r")  # clear line
        sys.stdout.write(line)
        sys.stdout.flush()

    def update(self, profile_id: str, tool_count: int = 0, turn_count: int = 0):
        """Mark one trace as completed and refresh the bar."""
        self.completed += 1
        self.tool_calls += tool_count
        self.turns += turn_count
        self._last_profile = profile_id
        self._render()

    def fail(self, profile_id: str):
        """Mark one trace as failed and refresh."""
        self.failed += 1
        self._last_profile = profile_id
        self._render()

    def finish(self):
        """Print final newline so the bar stays visible."""
        sys.stdout.write("\n")
        sys.stdout.flush()


def _pick_max_turns(profile: PatientProfile) -> int:
    """Pick turn count. Minimum 4 turns to give the agent time to use tools and
    develop the conversation enough for classifiers to differentiate modes.
    10% = 4, 40% = 5-6, 35% = 7-8, 15% = 9-10."""
    roll = random.random()
    if roll < 0.10:
        return 4
    elif roll < 0.50:
        return random.choice([5, 6])
    elif roll < 0.85:
        return random.choice([7, 8])
    else:
        return random.choice([9, 10])


@tracer.observe(span_type="function")
def run_conversation(
    profile: PatientProfile,
    max_turns: int = 0,
    model: str = "claude-haiku-4-5-20251001",
    verbose: bool = False,
    session_id: str = "",
) -> dict:
    """Run a full multi-turn conversation for one patient profile.

    The agent talks to a Haiku-powered patient simulator. Returns the trace.
    Each call creates one trace in Judgment with full conversation + tool spans.
    """
    if max_turns <= 0:
        max_turns = _pick_max_turns(profile)

    # Set Judgment trace metadata
    if session_id:
        tracer.set_session_id(session_id)
    tracer.set_customer_id(profile.id)
    tracer.set_attributes({
        "patient.mode": profile.mode.value,
        "patient.communication_style": profile.communication_style.value,
        "patient.age": profile.age,
        "patient.sex": profile.sex,
        "patient.chief_complaint": profile.chief_complaint,
        "patient.expected_urgency": profile.expected_urgency or "unknown",
        "patient.edge_case_tags": json.dumps(profile.edge_case_tags),
        "patient.red_flags_present": str(profile.red_flags_present),
        "patient.max_turns": max_turns,
    })

    agent = HealthAgent(model=model)
    agent.reset(profile_id=profile.id, mode=profile.mode)
    patient = PatientSimulator(profile)

    # Start with patient's opening message
    patient_msg = patient.get_opening_message()
    tracer.set_input(json.dumps({
        "patient_id": profile.id,
        "mode": profile.mode.value,
        "chief_complaint": profile.chief_complaint,
        "communication_style": profile.communication_style.value,
        "opening_message": patient_msg,
    }))

    if verbose:
        print(f"\n{'='*60}")
        print(f"Profile: {profile.id} | Mode: {profile.mode.value} | Style: {profile.communication_style.value}")
        print(f"Chief complaint: {profile.chief_complaint}")
        print(f"{'='*60}")
        print(f"\n[Patient]: {patient_msg}\n")

    for turn in range(max_turns):
        # Agent responds
        agent_response = agent.run_turn(patient_msg)

        if verbose:
            print(f"[Judgment Health]: {agent_response[:200]}{'...' if len(agent_response) > 200 else ''}\n")

        # Check if agent is wrapping up
        if agent.is_wrapping_up(agent_response):
            if verbose:
                print("  >> Agent is wrapping up, ending conversation.")
            break

        # If not the last allowed turn, get patient response
        if turn < max_turns - 1:
            patient_msg = patient.respond(agent_response)
            if verbose:
                print(f"[Patient]: {patient_msg}\n")

    trace = agent.get_trace()
    trace.metadata["profile"] = profile.model_dump(mode="json")
    trace.metadata["expected_urgency"] = profile.expected_urgency
    trace.metadata["edge_case_tags"] = profile.edge_case_tags
    trace.metadata["red_flags_expected"] = profile.red_flags_present

    # Build a clean conversation transcript for Judgment classifiers.
    # Without this, {{trace}} only shows metadata and tool JSON — classifiers
    # never see the actual patient/agent dialogue.
    transcript_lines = []
    for t in trace.turns:
        label = "PATIENT" if t.role == "user" else "AGENT"
        transcript_lines.append(f"[{label}]: {t.content}")
    transcript = "\n\n".join(transcript_lines)

    # Set trace output for Judgment — includes both stats and the full dialogue
    tracer.set_output(json.dumps({
        "total_turns": trace.metadata.get("total_turns"),
        "tools_used": trace.metadata.get("tools_used"),
        "total_tool_calls": trace.metadata.get("total_tool_calls"),
        "conversation_transcript": transcript,
    }))

    return trace.model_dump(mode="json")


def _assign_session_ids(profiles: list[PatientProfile]) -> list[str]:
    """Assign session IDs: 70% standalone (no session), 30% grouped in clusters of 2-4.

    Returns a list of session IDs parallel to profiles. Empty string = no session.
    """
    n = len(profiles)
    session_ids = [""] * n
    indices = list(range(n))
    random.shuffle(indices)

    # 30% get sessions, grouped in clusters of 2-4
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
    profiles: list[PatientProfile],
    max_turns: int = 0,
    model: str = "claude-haiku-4-5-20251001",
    concurrency: int = 3,
    verbose: bool = False,
    progress_callback: callable = None,
) -> list[dict]:
    """Run conversations for a batch of profiles.

    Uses thread pool for concurrent execution (IO-bound API calls).
    70% of traces are standalone, 30% are grouped into sessions of 2-4.
    """
    session_ids = _assign_session_ids(profiles)
    session_count = sum(1 for s in session_ids if s)
    unique_sessions = len(set(s for s in session_ids if s))

    traces = []
    failed = []
    total = len(profiles)

    print(f"\n  Judgment Health Agent Runner")
    print(f"  {'─'*36}")
    print(f"  Conversations : {total}")
    print(f"  Model         : {model}")
    print(f"  Concurrency   : {concurrency}")
    print(f"  Sessions      : {unique_sessions} sessions ({session_count} traces), {total - session_count} standalone")
    print(f"  Output        : {OUTPUT_DIR}\n")

    bar = ProgressBar(total)
    bar._render()  # show empty bar immediately
    start_time = time.time()

    def _emit_progress(profile_id, tool_count=0, turn_count=0, error=None):
        """Update terminal bar and optionally fire web callback."""
        if error:
            bar.fail(profile_id)
        else:
            bar.update(profile_id, tool_count, turn_count)
        if progress_callback:
            progress_callback({
                "type": "error" if error else "progress",
                "completed": bar.completed,
                "failed": bar.failed,
                "total": total,
                "profile_id": profile_id,
                "tool_count": tool_count,
                "turn_count": turn_count,
                "avg_tools": bar.tool_calls / max(bar.completed, 1),
                "avg_turns": bar.turns / max(bar.completed, 1),
                "elapsed": time.time() - start_time,
                "error": str(error) if error else None,
            })

    if concurrency == 1:
        # Sequential — easier to debug
        for i, profile in enumerate(profiles):
            try:
                sid = session_ids[i]
                trace = run_conversation(profile, max_turns, model, verbose, sid)
                traces.append(trace)
                tool_count = trace["metadata"]["total_tool_calls"]
                turns = trace["metadata"]["total_turns"]
                _emit_progress(profile.id, tool_count, turns)
            except Exception as e:
                _emit_progress(profile.id, error=e)
                failed.append({"profile_id": profile.id, "error": str(e)})
    else:
        # Concurrent
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
                    _emit_progress(profile.id, tool_count, turns)
                except Exception as e:
                    _emit_progress(profile.id, error=e)
                    failed.append({"profile_id": profile.id, "error": str(e)})

    bar.finish()
    elapsed = time.time() - start_time

    print(f"\n  {'═'*36}")
    print(f"  ✓ Completed : {len(traces)}/{total}")
    if failed:
        print(f"  ✗ Failed    : {len(failed)}")
    print(f"  ⏱ Time      : {elapsed:.1f}s ({elapsed/max(len(traces),1):.1f}s avg)")

    if traces:
        total_tokens = sum(t["metadata"].get("total_input_tokens", 0) + t["metadata"].get("total_output_tokens", 0) for t in traces)
        total_tools = sum(t["metadata"].get("total_tool_calls", 0) for t in traces)
        avg_turns = sum(t["metadata"].get("total_turns", 0) for t in traces) / len(traces)
        print(f"  📊 Tokens    : {total_tokens:,}")
        print(f"  🔧 Tools     : {total_tools} ({total_tools/len(traces):.1f}/conv)")
        print(f"  💬 Turns     : {avg_turns:.1f} avg")

    if progress_callback:
        progress_callback({
            "type": "done",
            "completed": len(traces),
            "failed": len(failed),
            "total": total,
            "elapsed": elapsed,
        })

    return traces


def main():
    parser = argparse.ArgumentParser(description="Judgment Health Agent Runner")
    parser.add_argument("--count", type=int, default=5, help="Number of conversations to run (default: 5)")
    parser.add_argument("--profile", type=str, help="Run a single profile by ID (e.g., patient_0042)")
    parser.add_argument("--generate-only", action="store_true", help="Generate profiles without running agent")
    parser.add_argument("--max-turns", type=int, default=0, help="Max turns per conversation (0 = auto-vary by mode/style)")
    parser.add_argument("--model", type=str, default="claude-haiku-4-5-20251001", help="Claude model to use")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrent conversations (default: 3)")
    parser.add_argument("--verbose", action="store_true", help="Print conversation details")
    parser.add_argument("--seed", type=int, default=-1, help="Random seed (-1 = fully random each run)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    # Generate or load profiles
    if not PROFILES_PATH.exists() or args.generate_only:
        print(f"Generating {max(args.count, 1050)} patient profiles...")
        profiles = generate_profiles(max(args.count, 1050), seed=args.seed)
        save_profiles(profiles, PROFILES_PATH)
        print(f"Saved to {PROFILES_PATH}")
        if args.generate_only:
            return

    profiles = load_profiles(PROFILES_PATH)
    print(f"Loaded {len(profiles)} profiles from {PROFILES_PATH}")

    # Filter if specific profile requested
    if args.profile:
        profiles = [p for p in profiles if p.id == args.profile]
        if not profiles:
            print(f"Profile '{args.profile}' not found.")
            return
        args.count = 1

    # Select subset
    profiles = profiles[:args.count]

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

        # Also save a summary
        summary = {
            "run_timestamp": timestamp,
            "total_conversations": len(traces),
            "model": args.model,
            "mode_distribution": {},
            "avg_turns": 0,
            "avg_tool_calls": 0,
            "total_tokens": 0,
        }
        for t in traces:
            mode = t.get("mode", "unknown")
            summary["mode_distribution"][mode] = summary["mode_distribution"].get(mode, 0) + 1
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
