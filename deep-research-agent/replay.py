"""Replay exact profiles from a Judgment JSONL export.

Usage:
    modal run --env internal-agents-l replay.py
"""

from __future__ import annotations

import json
import time
import os
from typing import Optional

import modal

# ---------------------------------------------------------------------------
# Modal app & image (reuse from modal_research.py)
# ---------------------------------------------------------------------------

app = modal.App("deep-research-replay")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "anthropic>=0.39.0",
        "pydantic>=2.0.0",
        "google-genai>=1.0.0",
        "tqdm>=4.60.0",
        "judgeval>=0.1.0",
        "packaging",
    )
    .add_local_file("agent.py", "/app/agent.py", copy=True)
    .add_local_file("tools.py", "/app/tools.py", copy=True)
    .add_local_file("models.py", "/app/models.py", copy=True)
    .add_local_file("tracing.py", "/app/tracing.py", copy=True)
    .add_local_file("requester_simulator.py", "/app/requester_simulator.py", copy=True)
    .add_local_file("run.py", "/app/run.py", copy=True)
    .add_local_file("replay_profiles.json", "/app/replay_profiles.json", copy=True)
    .run_commands(
        "useradd -m -s /bin/bash -u 1000 evaluser",
        "chown -R evaluser:evaluser /app",
    )
    .dockerfile_commands("USER evaluser")
    .env({
        "HOME": "/home/evaluser",
        "USER": "evaluser",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
)

secrets = [
    modal.Secret.from_name("Research-Agent-Anthropic-Key"),
    modal.Secret.from_name("Gemini-key"),
    modal.Secret.from_name("JudgmentAPI_Key"),
    modal.Secret.from_name("judgment-org-id"),
]

_ENV_ALIASES = {
    "ANTHROPIC_API_KEY": ["ANTHROPIC_API_KEY", "Research_Agent_Anthropic_Key"],
    "GEMINI_API_KEY": ["GEMINI_API_KEY", "Gemini_key"],
    "JUDGMENT_API_KEY": ["JUDGMENT_API_KEY", "Judgment_API_Key"],
    "JUDGMENT_ORG_ID": ["JUDGMENT_ORG_ID", "Judgment_internal_agent_org_id", "judgment_org_id"],
}


def _ensure_env_vars():
    import os
    for canonical, aliases in _ENV_ALIASES.items():
        if os.environ.get(canonical):
            continue
        for alias in aliases:
            val = os.environ.get(alias)
            if val:
                os.environ[canonical] = val
                break


# ---------------------------------------------------------------------------
# Session depth (same as modal_research.py)
# ---------------------------------------------------------------------------

SESSION_DEPTH = {
    ("Simple", "Overview"):         (2, 2),
    ("Simple", "Detailed"):         (3, 2),
    ("Simple", "Exhaustive"):       (4, 3),
    ("Moderate", "Overview"):       (3, 2),
    ("Moderate", "Detailed"):       (4, 3),
    ("Moderate", "Exhaustive"):     (5, 3),
    ("Complex", "Overview"):        (4, 3),
    ("Complex", "Detailed"):        (5, 3),
    ("Complex", "Exhaustive"):      (6, 3),
    ("Expert_Level", "Overview"):   (5, 3),
    ("Expert_Level", "Detailed"):   (6, 3),
    ("Expert_Level", "Exhaustive"): (8, 3),
}


# ---------------------------------------------------------------------------
# Worker: one replay per container
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=secrets,
    timeout=1200,
    cpu=1,
    memory=2048,
)
def run_single(profile_dict: dict) -> dict:
    """Run the research agent on a single replayed profile."""
    import sys
    import uuid
    sys.path.insert(0, "/app")
    _ensure_env_vars()

    from models import (
        QueryProfile, ResearchType, Complexity, TimeSensitivity,
        RequesterPersona, DepthPreference,
    )
    from agent import ResearchAgent
    from tracing import flush_and_shutdown

    p = profile_dict
    profile = QueryProfile(
        id=p["id"],
        query=p["query"],
        research_type=ResearchType(p["research_type"]),
        domain=p["domain"],
        complexity=Complexity(p["complexity"]),
        time_sensitivity=TimeSensitivity(p["time_sensitivity"]),
        requester_persona=RequesterPersona(p["requester_persona"]),
        depth_preference=DepthPreference(p["depth_preference"]),
        sub_questions=p.get("sub_questions", []),
        expected_sources=p.get("expected_sources", 5),
        edge_case_tags=p.get("edge_case_tags", []),
    )

    depth_key = (profile.complexity.value, profile.depth_preference.value)
    max_turns, max_tool_rounds = SESSION_DEPTH.get(depth_key, (6, 3))

    os.environ["JUDGMENT_SESSION_ID"] = f"replay-{profile.id}-{uuid.uuid4().hex[:8]}"

    start = time.time()
    try:
        agent = ResearchAgent(
            profile=profile,
            verbose=True,
            max_conversation_turns=max_turns,
            max_tool_rounds=max_tool_rounds,
        )
        trace = agent.run_session()
        result = {
            "profile_id": profile.id,
            "query": profile.query,
            "domain": profile.domain,
            "resolved": True,
            "turns": len(trace.turns),
            "tool_calls": len(trace.tool_calls),
            "tokens": trace.total_tokens,
            "duration": trace.duration,
            "error": None,
        }
    except Exception as e:
        result = {
            "profile_id": profile.id,
            "query": profile.query,
            "domain": profile.domain,
            "resolved": False,
            "turns": 0,
            "tool_calls": 0,
            "tokens": 0,
            "duration": time.time() - start,
            "error": str(e),
        }

    flush_and_shutdown()

    status = "OK" if result["resolved"] else "FAIL"
    print(f"[{status}] {result['profile_id']} — {result['query'][:60]}")
    print(f"  {result['turns']} turns, {result['tool_calls']} tools, {result['tokens']} tok, {result['duration']:.0f}s")
    return result


# ---------------------------------------------------------------------------
# Orchestrator: fan out all profiles
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=secrets,
    timeout=14400,
)
def run_replay() -> dict:
    """Load profiles and fan out."""
    import sys
    sys.path.insert(0, "/app")

    with open("/app/replay_profiles.json") as f:
        profiles = json.load(f)

    print(f"Replaying {len(profiles)} profiles...")

    raw_results = list(run_single.map(
        profiles,
        return_exceptions=True,
        wrap_returned_exceptions=False,
    ))

    results = []
    for i, r in enumerate(raw_results):
        if isinstance(r, Exception):
            results.append({
                "profile_id": profiles[i]["id"],
                "resolved": False,
                "error": str(r),
            })
        else:
            results.append(r)

    resolved = sum(1 for r in results if r.get("resolved"))
    errors = sum(1 for r in results if r.get("error"))
    total_tokens = sum(r.get("tokens", 0) for r in results)

    print(f"\n{'='*60}")
    print(f"REPLAY COMPLETE")
    print(f"  Resolved: {resolved}/{len(results)}")
    print(f"  Errors:   {errors}")
    print(f"  Tokens:   {total_tokens:,}")
    print(f"{'='*60}")

    return {"total": len(results), "resolved": resolved, "errors": errors, "tokens": total_tokens}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@app.local_entrypoint()
def main():
    summary = run_replay.remote()
    print(f"\nReplay: {summary['resolved']}/{summary['total']} resolved, {summary['tokens']:,} tokens")
