"""Modal app for deep research agent — synthetic evaluation sandbox.

Usage:
    # Deploy to internal-agents-l environment
    modal deploy modal_research.py --env internal-agents-l

    # Run from CLI (default: 10 tasks)
    modal run modal_research.py --env internal-agents-l

    # Run with custom count
    modal run modal_research.py --env internal-agents-l --count 20

    # Debug: shell into the container
    modal shell modal_research.py --env internal-agents-l
"""

from __future__ import annotations

import collections
import json
import random
import uuid as _uuid
from typing import Optional

import modal

# ---------------------------------------------------------------------------
# App & image
# ---------------------------------------------------------------------------

app = modal.App("deep-research-eval")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "anthropic>=0.39.0",
        "pydantic>=2.0.0",
        "google-genai>=1.0.0",
        "tqdm>=4.60.0",
        "judgeval>=0.1.0",
        "packaging",  # required by judgeval tracer internals
    )
    .add_local_file("agent.py", "/app/agent.py", copy=True)
    .add_local_file("tools.py", "/app/tools.py", copy=True)
    .add_local_file("models.py", "/app/models.py", copy=True)
    .add_local_file("tracing.py", "/app/tracing.py", copy=True)
    .add_local_file("requester_simulator.py", "/app/requester_simulator.py", copy=True)
    .add_local_file("run.py", "/app/run.py", copy=True)
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

results_volume = modal.Volume.from_name("research-results", create_if_missing=True)

# NOTE: Modal secrets expose env vars based on the key names used when creating
# the secret in the Modal dashboard.  If the secret key doesn't exactly match
# what the code expects (ANTHROPIC_API_KEY, GEMINI_API_KEY, etc.), we remap in
# _ensure_env_vars() at the top of each worker.
secrets = [
    modal.Secret.from_name("Research-Agent-Anthropic-Key"),
    modal.Secret.from_name("Gemini-key"),
    modal.Secret.from_name("JudgmentAPI_Key"),
    modal.Secret.from_name("judgment-org-id"),
]

# Mapping: (expected_env_var) → list of actual names exposed by Modal secrets
# Modal converts secret names to env vars with underscores (dashes → underscores)
_ENV_ALIASES = {
    "ANTHROPIC_API_KEY": [
        "ANTHROPIC_API_KEY",
        "Research_Agent_Anthropic_Key",
    ],
    "GEMINI_API_KEY": [
        "GEMINI_API_KEY",
        "Gemini_key",
    ],
    "JUDGMENT_API_KEY": [
        "JUDGMENT_API_KEY",
        "Judgment_API_Key",
    ],
    "JUDGMENT_ORG_ID": [
        "JUDGMENT_ORG_ID",
        "Judgment_internal_agent_org_id",
        "judgment_org_id",
    ],
}


def _ensure_env_vars():
    """Remap secret env vars so the app code finds them under canonical names."""
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
# CycleDeck — guarantees proportional category coverage per cycle
# ---------------------------------------------------------------------------

class CycleDeck:
    """Card-deck distribution: builds a shuffled deck proportional to weights,
    deals from the top.  When the deck empties it rebuilds.  This guarantees
    exact proportional coverage over each full cycle.
    """

    def __init__(self, name: str, weights: dict[str, float], cycle_size: int = 60):
        self.name = name
        self.weights = weights
        self.cycle_size = max(cycle_size, len(weights) * 2)
        self.deck: list[str] = []
        self._rebuild()

    def _rebuild(self):
        items = list(self.weights.keys())
        total_w = sum(max(self.weights[i], 0) for i in items)
        if total_w == 0:
            per = self.cycle_size // len(items)
            counts = {i: max(per, 1) for i in items}
        else:
            counts = {}
            for item in items:
                counts[item] = max(round(self.weights[item] / total_w * self.cycle_size), 1)
        # Fix rounding to hit cycle_size exactly
        diff = self.cycle_size - sum(counts.values())
        sorted_items = sorted(items, key=lambda x: counts[x], reverse=(diff < 0))
        for i in range(abs(diff)):
            counts[sorted_items[i % len(sorted_items)]] += 1 if diff > 0 else -1
        self.deck = []
        for item in items:
            self.deck.extend([item] * max(counts[item], 0))
        random.shuffle(self.deck)

    def draw(self, n: int) -> list[str]:
        result: list[str] = []
        while len(result) < n:
            if not self.deck:
                self._rebuild()
            take = min(n - len(result), len(self.deck))
            result.extend(self.deck[:take])
            self.deck = self.deck[take:]
        return result


# ---------------------------------------------------------------------------
# Category definitions & queries (mirrors dashboard.py)
# ---------------------------------------------------------------------------

RESEARCH_DOMAINS = [
    "AI/ML", "Finance", "Healthcare", "Climate", "Geopolitics", "Cybersecurity",
]

REQUESTER_PERSONAS = [
    "Executive", "Academic", "Journalist", "Student", "Analyst", "Curious Generalist",
]

RESEARCH_TYPES = [
    "Literature Review", "Market Analysis", "Technical Deep Dive",
    "Fact Checking", "Comparative Analysis", "Trend Research",
]

# Default even weights
DEFAULT_DOMAIN_WEIGHTS = {d: 1.0 for d in RESEARCH_DOMAINS}
DEFAULT_PERSONA_WEIGHTS = {p: 1.0 for p in REQUESTER_PERSONAS}
DEFAULT_TYPE_WEIGHTS = {t: 1.0 for t in RESEARCH_TYPES}

# Session depth tiers — map (complexity, depth_preference) to
# (max_conversation_turns, max_tool_rounds) for trace length variety.
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

DOMAIN_QUERIES = {
    "AI/ML": [
        "What are the latest advances in large language model reasoning capabilities?",
        "Compare transformer architectures for real-time inference at the edge",
        "Analyze the state of AI safety research and alignment techniques in 2025",
        "What is the current landscape of open-source foundation models?",
        "Evaluate multimodal AI systems for enterprise document processing",
        "How are synthetic data generation techniques improving model training?",
        "What are the leading approaches to reducing hallucinations in LLMs?",
        "Analyze the economic impact of AI code generation tools on software development",
        "Compare federated learning frameworks for privacy-preserving healthcare AI",
        "What is the state of neuromorphic computing for energy-efficient AI?",
        "Evaluate retrieval-augmented generation architectures for enterprise search",
        "How are AI agents being used for autonomous scientific discovery?",
        "Compare reinforcement learning from human feedback methods across labs",
        "What are the current benchmarks and limitations of AI for mathematical reasoning?",
        "Analyze the competitive landscape of AI chip startups vs incumbent chipmakers",
    ],
    "Finance": [
        "Analyze the impact of central bank digital currencies on traditional banking",
        "What are the emerging trends in decentralized finance regulation?",
        "Compare quantitative trading strategies using alternative data sources",
        "Evaluate the global sovereign debt landscape and default risk indicators",
        "What is the outlook for private credit markets in 2025-2026?",
        "How are embedded finance platforms reshaping consumer lending?",
        "Analyze the impact of Basel IV implementation on regional banks",
        "What are the key drivers of insurance-linked securities growth?",
        "Compare real-time payment system adoption across G20 economies",
        "Evaluate the risks and opportunities in commercial real estate debt markets",
        "How is tokenization of real-world assets progressing in capital markets?",
        "What is the current state of ESG scoring methodologies and their reliability?",
        "Analyze the impact of AI-driven robo-advisors on wealth management margins",
        "Compare cross-border payment solutions and their settlement efficiency",
        "What are the systemic risks posed by non-bank financial intermediaries?",
    ],
    "Healthcare": [
        "What are the latest clinical trial results for mRNA-based cancer therapies?",
        "Analyze the adoption of AI diagnostics in radiology departments worldwide",
        "Compare CRISPR gene therapy approaches for sickle cell disease treatment",
        "Evaluate the impact of wearable health monitors on preventive care outcomes",
        "What is the state of antibiotic resistance research and new drug pipeline?",
        "How are digital twins being used for personalized treatment planning?",
        "Analyze the global supply chain vulnerabilities for pharmaceutical ingredients",
        "What are the leading approaches to early Alzheimer's detection via biomarkers?",
        "Compare telehealth utilization rates and outcomes across rural vs urban areas",
        "Evaluate the effectiveness of GLP-1 receptor agonists beyond diabetes treatment",
        "What is the state of xenotransplantation research after recent breakthroughs?",
        "How are hospital systems implementing ambient clinical documentation AI?",
        "Analyze the impact of social determinants of health data on care delivery models",
        "Compare CAR-T cell therapy outcomes across different cancer types and providers",
        "What are the regulatory pathways for adaptive clinical trial designs?",
    ],
    "Climate": [
        "Evaluate the effectiveness of carbon capture technologies deployed at scale",
        "What are the latest projections for Arctic sea ice loss by 2030?",
        "Compare renewable energy storage solutions for grid-scale deployment",
        "Analyze the economic impact of climate migration on coastal cities",
        "What is the current state of methane emissions monitoring from satellites?",
        "How are carbon credit markets evolving after recent integrity scandals?",
        "Analyze the viability of direct air capture at costs below $200 per ton",
        "What are the leading approaches to climate-resilient agriculture in arid regions?",
        "Compare offshore wind deployment costs and timelines across major markets",
        "Evaluate the role of nuclear fusion timeline projections on energy policy",
        "What is the impact of permafrost thawing on global greenhouse gas budgets?",
        "How are insurance markets pricing climate risk for coastal properties?",
        "Analyze green hydrogen production costs and infrastructure readiness by region",
        "Compare biodiversity loss metrics and their relationship to climate change",
        "What are the current debates around solar radiation management governance?",
    ],
    "Geopolitics": [
        "Analyze the shifting dynamics of semiconductor supply chain geopolitics",
        "What are the implications of Arctic shipping routes on global trade?",
        "Compare defense spending trends among NATO members post-2024",
        "Evaluate the impact of rare earth mineral access on clean energy transitions",
        "What is the state of global food security and grain export dependencies?",
        "How is the BRICS expansion reshaping multilateral economic institutions?",
        "Analyze the geopolitical implications of subsea cable infrastructure control",
        "What are the key flashpoints in South China Sea territorial disputes?",
        "Compare space militarization policies among the US, China, and EU",
        "Evaluate the impact of US-China tech decoupling on global AI development",
        "What is the state of nuclear proliferation risks in the Middle East?",
        "How are water scarcity conflicts emerging in Central Asia and the Nile Basin?",
        "Analyze the role of private military companies in contemporary conflicts",
        "Compare election security measures and foreign interference patterns globally",
        "What are the economic impacts of sanctions regimes on targeted nations?",
    ],
    "Cybersecurity": [
        "Analyze the evolution of ransomware tactics targeting critical infrastructure",
        "What are the most effective zero-trust architecture implementations?",
        "Compare post-quantum cryptography standards and migration timelines",
        "Evaluate the state of AI-powered threat detection in enterprise SOCs",
        "What are the emerging attack vectors for IoT and smart city systems?",
        "How are supply chain attacks evolving after major incidents like SolarWinds?",
        "Analyze the effectiveness of bug bounty programs vs traditional penetration testing",
        "What are the leading approaches to securing large language model deployments?",
        "Compare national cybersecurity strategies and incident response frameworks",
        "Evaluate the state of identity and access management for hybrid cloud environments",
        "What are the risks of deepfake technology for corporate social engineering?",
        "How are automotive manufacturers addressing connected vehicle cybersecurity?",
        "Analyze the impact of NIS2 directive on European cybersecurity compliance",
        "Compare threat intelligence sharing platforms and their adoption rates",
        "What are the current capabilities and limitations of automated vulnerability patching?",
    ],
}


# ---------------------------------------------------------------------------
# Profile generation (standalone — no Streamlit dependency)
# ---------------------------------------------------------------------------

_recent_queries: collections.deque = collections.deque(maxlen=45)


def _pick_query(domain: str) -> str:
    """Pick a query for the domain, avoiding recent repeats."""
    pool = DOMAIN_QUERIES.get(domain, DOMAIN_QUERIES["AI/ML"])
    available = [q for q in pool if q not in _recent_queries]
    if not available:
        available = pool
    pick = random.choice(available)
    _recent_queries.append(pick)
    return pick


def generate_profile(profile_id: str, domain: str, persona_name: str, research_type_name: str):
    """Generate a synthetic QueryProfile for a run."""
    import sys
    sys.path.insert(0, "/app")
    from models import (
        QueryProfile, ResearchType, Complexity, TimeSensitivity,
        RequesterPersona, DepthPreference,
    )

    persona_map = {
        "Executive": RequesterPersona.EXECUTIVE,
        "Academic": RequesterPersona.ACADEMIC,
        "Journalist": RequesterPersona.JOURNALIST,
        "Student": RequesterPersona.STUDENT,
        "Analyst": RequesterPersona.ANALYST,
        "Curious Generalist": RequesterPersona.CURIOUS_GENERALIST,
    }
    type_map = {
        "Literature Review": ResearchType.LITERATURE_REVIEW,
        "Market Analysis": ResearchType.MARKET_ANALYSIS,
        "Technical Deep Dive": ResearchType.TECHNICAL_DEEP_DIVE,
        "Fact Checking": ResearchType.FACT_CHECKING,
        "Comparative Analysis": ResearchType.COMPARATIVE_ANALYSIS,
        "Trend Research": ResearchType.TREND_RESEARCH,
    }

    query = _pick_query(domain)
    return QueryProfile(
        id=profile_id,
        query=query,
        research_type=type_map[research_type_name],
        domain=domain,
        complexity=random.choice(list(Complexity)),
        time_sensitivity=random.choice(list(TimeSensitivity)),
        requester_persona=persona_map[persona_name],
        depth_preference=random.choice(list(DepthPreference)),
    )


# ---------------------------------------------------------------------------
# Deck state persistence (via volume)
# ---------------------------------------------------------------------------

_DECK_STATE_PATH = "/results/state/.distribution_state.json"


def _save_deck_state(decks: dict[str, CycleDeck]):
    """Persist remaining deck cards to volume."""
    import os
    os.makedirs(os.path.dirname(_DECK_STATE_PATH), exist_ok=True)
    state = {name: deck.deck for name, deck in decks.items()}
    with open(_DECK_STATE_PATH, "w") as f:
        json.dump(state, f)


def _load_deck_state() -> dict[str, list[str]]:
    """Load persisted deck state from volume."""
    import os
    if os.path.exists(_DECK_STATE_PATH):
        try:
            with open(_DECK_STATE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


# ---------------------------------------------------------------------------
# Worker: one research session per container
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=secrets,
    volumes={"/results": results_volume},
    timeout=1200,  # 20 min per session
    cpu=1,
    memory=2048,
)
def run_single(task_spec: dict) -> dict:
    """Run the research agent on a single synthetic profile."""
    import sys
    import os
    import time
    sys.path.insert(0, "/app")
    _ensure_env_vars()

    profile_id = task_spec["profile_id"]
    domain = task_spec["domain"]
    persona = task_spec["persona"]
    research_type = task_spec["research_type"]
    forced_sentiment = task_spec.get("forced_sentiment")  # None for normal runs

    # Set session ID for tracing
    os.environ["JUDGMENT_SESSION_ID"] = f"modal-{profile_id}-{_uuid.uuid4().hex[:8]}"

    from models import QueryProfile
    from agent import ResearchAgent
    from tracing import flush_and_shutdown

    # Build profile
    profile = generate_profile(profile_id, domain, persona, research_type)

    # Look up session depth based on profile attributes
    depth_key = (profile.complexity.value, profile.depth_preference.value)
    max_turns, max_tool_rounds = SESSION_DEPTH.get(depth_key, (6, 3))

    # Run session
    start = time.time()
    try:
        agent = ResearchAgent(profile=profile, verbose=False,
                              max_conversation_turns=max_turns,
                              max_tool_rounds=max_tool_rounds,
                              forced_sentiment=forced_sentiment)
        trace = agent.run_session()

        result = {
            "profile_id": profile_id,
            "domain": domain,
            "persona": persona,
            "research_type": research_type,
            "resolved": True,
            "turns": len(trace.turns),
            "tool_calls": len(trace.tool_calls),
            "tokens": trace.total_tokens,
            "duration": trace.duration,
            "final_report_length": len(trace.final_report) if trace.final_report else 0,
            "error": None,
        }

        # Save trace to volume
        from pathlib import Path
        out_dir = Path(f"/results/traces/{profile_id}")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "trace.json").write_text(trace.model_dump_json(indent=2))

    except Exception as e:
        result = {
            "profile_id": profile_id,
            "domain": domain,
            "persona": persona,
            "research_type": research_type,
            "resolved": False,
            "turns": 0,
            "tool_calls": 0,
            "tokens": 0,
            "duration": time.time() - start,
            "final_report_length": 0,
            "error": str(e),
        }

    # Flush traces before container exits
    flush_and_shutdown()
    results_volume.commit()

    status = "OK" if result["resolved"] else "FAIL"
    err_msg = f" — {result['error']}" if result.get("error") else ""
    print(f"[{status}] {profile_id} ({domain}/{persona}/{research_type}) "
          f"{result['turns']} turns, {result['tokens']} tok, "
          f"{result['duration']:.0f}s{err_msg}")
    return result


# ---------------------------------------------------------------------------
# Orchestrator: generate profiles then fan out
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=secrets,
    volumes={"/results": results_volume},
    timeout=14400,  # 4 hours
)
def run_batch(count: int = 10, seed: Optional[int] = None) -> dict:
    """Generate research profiles with CycleDeck, then run the agent on each."""
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    if seed is not None:
        random.seed(seed)

    # Restore deck state from previous runs
    results_volume.reload()
    saved = _load_deck_state()

    cycle_size = max(count * 6, 60)
    domain_deck = CycleDeck("domain", DEFAULT_DOMAIN_WEIGHTS, cycle_size=cycle_size)
    persona_deck = CycleDeck("persona", DEFAULT_PERSONA_WEIGHTS, cycle_size=cycle_size)
    type_deck = CycleDeck("rtype", DEFAULT_TYPE_WEIGHTS, cycle_size=cycle_size)

    # Restore leftover cards from previous batches
    if "domain" in saved:
        valid = [c for c in saved["domain"] if c in DEFAULT_DOMAIN_WEIGHTS]
        if valid:
            domain_deck.deck = valid
    if "persona" in saved:
        valid = [c for c in saved["persona"] if c in DEFAULT_PERSONA_WEIGHTS]
        if valid:
            persona_deck.deck = valid
    if "rtype" in saved:
        valid = [c for c in saved["rtype"] if c in DEFAULT_TYPE_WEIGHTS]
        if valid:
            type_deck.deck = valid

    decks = {"domain": domain_deck, "persona": persona_deck, "rtype": type_deck}

    # Draw from decks
    domains = domain_deck.draw(count)
    personas = persona_deck.draw(count)
    research_types = type_deck.draw(count)

    # Build task specs
    task_specs = []
    for i in range(count):
        pid = f"run_{_uuid.uuid4().hex[:8]}"
        task_specs.append({
            "profile_id": pid,
            "domain": domains[i],
            "persona": personas[i],
            "research_type": research_types[i],
        })

    print(f"Running {count} research sessions...")
    print(f"Domains: {dict(collections.Counter(domains))}")
    print(f"Personas: {dict(collections.Counter(personas))}")
    print(f"Types: {dict(collections.Counter(research_types))}")

    # Fan out
    raw_results = list(run_single.map(
        task_specs,
        return_exceptions=True,
        wrap_returned_exceptions=False,
    ))

    # Handle exceptions
    results = []
    for i, r in enumerate(raw_results):
        if isinstance(r, Exception):
            results.append({
                "profile_id": task_specs[i]["profile_id"],
                "resolved": False,
                "error": str(r),
                "domain": task_specs[i]["domain"],
                "persona": task_specs[i]["persona"],
                "research_type": task_specs[i]["research_type"],
            })
        else:
            results.append(r)

    # Persist deck state for next batch
    _save_deck_state(decks)
    results_volume.commit()

    # Aggregate
    resolved = sum(1 for r in results if r.get("resolved"))
    errors = sum(1 for r in results if r.get("error"))
    total_tokens = sum(r.get("tokens", 0) for r in results)
    total_turns = sum(r.get("turns", 0) for r in results)
    total_tools = sum(r.get("tool_calls", 0) for r in results)
    total_duration = sum(r.get("duration", 0) for r in results)

    now = datetime.now(timezone.utc)
    summary = {
        "run_id": now.strftime("%Y-%m-%d_%H%M%S"),
        "evaluated_at": now.isoformat(),
        "total": len(results),
        "resolved": resolved,
        "errors": errors,
        "total_tokens": total_tokens,
        "avg_turns": round(total_turns / max(len(results), 1), 1),
        "avg_tool_calls": round(total_tools / max(len(results), 1), 1),
        "avg_duration": round(total_duration / max(len(results), 1), 1),
        "results": results,
    }

    out_dir = Path(f"/results/runs/{summary['run_id']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "research_summary.json").write_text(json.dumps(summary, indent=2))
    results_volume.commit()

    print(f"\n{'='*60}")
    print(f"RESEARCH EVAL SUMMARY — {summary['run_id']}")
    print(f"  Resolved: {resolved}/{len(results)}")
    print(f"  Errors:   {errors}/{len(results)}")
    print(f"  Tokens:   {total_tokens:,}")
    print(f"  Avg turns: {summary['avg_turns']}, Avg tools: {summary['avg_tool_calls']}")
    print(f"  Avg duration: {summary['avg_duration']}s")
    print(f"{'='*60}")

    return summary


# ---------------------------------------------------------------------------
# Cron: trickle traffic mimicking production (~10/hr)
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=secrets,
    volumes={"/results": results_volume},
    schedule=modal.Cron("*/30 * * * *"),  # every 30 minutes
    timeout=14400,
)
def cron_research():
    """Scheduled research eval — conservative trickle traffic (~30 runs/day)."""
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo

    PT = ZoneInfo("America/Los_Angeles")
    now_pt = datetime.now(PT)
    hour = now_pt.hour
    is_weekend = now_pt.weekday() >= 5

    # --- Ramp: linear growth over RAMP_DAYS, then plateau ---
    LAUNCH_DATE = "2026-03-13"
    RAMP_DAYS = 30          # slower ramp (was 14)
    launch = datetime.strptime(LAUNCH_DATE, "%Y-%m-%d").replace(tzinfo=PT)
    days_elapsed = (now_pt - launch).total_seconds() / 86400
    ramp = min(1.0, max(0.0, days_elapsed / RAMP_DAYS))

    # --- Daily cap: track how many sessions ran today ---
    DAILY_CAP = 40          # hard ceiling per day
    from pathlib import Path
    results_volume.reload()
    counter_path = Path(f"/results/state/.daily_count_{now_pt.strftime('%Y-%m-%d')}.json")
    daily_so_far = 0
    if counter_path.exists():
        try:
            daily_so_far = json.loads(counter_path.read_text()).get("count", 0)
        except Exception:
            pass

    if daily_so_far >= DAILY_CAP:
        print(f"[cron] {now_pt.isoformat()} — daily cap reached ({daily_so_far}/{DAILY_CAP})")
        return {"skipped": True, "reason": "daily_cap"}

    # --- Conservative traffic ranges (at ramp=1.0) ---
    # Target ~30-40/day weekday, ~15-20/day weekend
    # 2 ticks/hr × ~1-2 per tick during active hours
    if is_weekend:
        base_count = 1 if 10 <= hour < 20 else 0
    elif 9 <= hour < 18:  # business hours
        base_count = random.randint(1, 2)   # ~2-4/hr
    elif 18 <= hour < 22:  # evening
        base_count = 1                       # ~2/hr
    else:  # late night / early morning
        base_count = 0

    count = max(1, round(base_count * ramp)) if base_count > 0 else 0
    # Respect daily cap
    count = min(count, DAILY_CAP - daily_so_far)

    if count <= 0:
        print(f"[cron] {now_pt.isoformat()} — skipping (off-hours or cap)")
        return {"skipped": True}

    seed = int(time.time() * 1000) & 0x7FFFFFFF

    print(f"[cron] {now_pt.isoformat()} — {count} sessions (ramp={ramp:.0%}, today={daily_so_far}+{count}/{DAILY_CAP}), seed={seed}")
    result = run_batch.remote(count=count, seed=seed)

    # Update daily counter
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    counter_path.write_text(json.dumps({"count": daily_so_far + count}))
    results_volume.commit()

    return result


# ---------------------------------------------------------------------------
# Debug: test tracing inside the container
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=secrets,
    timeout=120,
)
def debug_tracing() -> str:
    """Debug function to test judgeval import and tracing init."""
    import sys
    import os
    sys.path.insert(0, "/app")
    _ensure_env_vars()

    lines = []
    lines.append(f"Python: {sys.version}")

    # 1. judgeval import
    try:
        import judgeval
        lines.append(f"judgeval import: OK v{judgeval.__version__}")
    except ImportError as e:
        lines.append(f"judgeval import: FAILED ImportError: {e}")
    except Exception as e:
        lines.append(f"judgeval import: FAILED {type(e).__name__}: {e}")

    # 2. env vars
    api_key = os.environ.get("JUDGMENT_API_KEY")
    org_id = os.environ.get("JUDGMENT_ORG_ID")
    lines.append(f"JUDGMENT_API_KEY: {'SET (' + api_key[:12] + '...)' if api_key else 'NOT SET'}")
    lines.append(f"JUDGMENT_ORG_ID: {'SET (' + org_id[:12] + '...)' if org_id else 'NOT SET'}")
    lines.append(f"ANTHROPIC_API_KEY: {'SET' if os.environ.get('ANTHROPIC_API_KEY') else 'NOT SET'}")
    lines.append(f"GEMINI_API_KEY: {'SET' if os.environ.get('GEMINI_API_KEY') else 'NOT SET'}")

    # 3. tracing init
    try:
        from tracing import get_tracer
        tracer = get_tracer()
        lines.append(f"get_tracer(): {tracer}")
        if tracer is None:
            lines.append("TRACING DISABLED — trying manual init...")
            if api_key:
                from judgeval import Judgeval
                lines.append("  Judgeval class imported OK")
                jclient = Judgeval(project_name="debug-test")
                lines.append(f"  Judgeval client: {jclient}")
                t = jclient.tracer.create()
                lines.append(f"  Manual tracer: {t}")
            else:
                lines.append("  No API key — cannot init")
        else:
            lines.append("TRACING IS WORKING")
    except Exception as e:
        import traceback
        lines.append(f"tracing init error: {type(e).__name__}: {e}")
        lines.append(traceback.format_exc())

    output = "\n".join(lines)
    print(output)
    return output


# ---------------------------------------------------------------------------
# Sentiment injection: generate traces with forced requester sentiments
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=secrets,
    volumes={"/results": results_volume},
    timeout=14400,
)
def run_sentiment_batch(sentiment: str, count: int = 25, seed: Optional[int] = None) -> dict:
    """Run a batch forcing a specific requester sentiment."""
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    if seed is not None:
        random.seed(seed)

    results_volume.reload()

    cycle_size = max(count * 6, 60)
    domain_deck = CycleDeck("domain", DEFAULT_DOMAIN_WEIGHTS, cycle_size=cycle_size)
    persona_deck = CycleDeck("persona", DEFAULT_PERSONA_WEIGHTS, cycle_size=cycle_size)
    type_deck = CycleDeck("rtype", DEFAULT_TYPE_WEIGHTS, cycle_size=cycle_size)

    domains = domain_deck.draw(count)
    personas = persona_deck.draw(count)
    research_types = type_deck.draw(count)

    task_specs = []
    for i in range(count):
        pid = f"sent_{sentiment[:4]}_{_uuid.uuid4().hex[:8]}"
        task_specs.append({
            "profile_id": pid,
            "domain": domains[i],
            "persona": personas[i],
            "research_type": research_types[i],
            "forced_sentiment": sentiment,
        })

    print(f"Running {count} {sentiment.upper()} sentiment sessions...")
    print(f"Domains: {dict(collections.Counter(domains))}")

    raw_results = list(run_single.map(
        task_specs,
        return_exceptions=True,
        wrap_returned_exceptions=False,
    ))

    results = []
    for i, r in enumerate(raw_results):
        if isinstance(r, Exception):
            results.append({
                "profile_id": task_specs[i]["profile_id"],
                "resolved": False,
                "error": str(r),
                "domain": task_specs[i]["domain"],
                "persona": task_specs[i]["persona"],
                "research_type": task_specs[i]["research_type"],
                "forced_sentiment": sentiment,
            })
        else:
            results.append(r)

    results_volume.commit()

    resolved = sum(1 for r in results if r.get("resolved"))
    errors = sum(1 for r in results if r.get("error"))
    total_tokens = sum(r.get("tokens", 0) for r in results)

    now = datetime.now(timezone.utc)
    summary = {
        "run_id": f"sentiment_{sentiment}_{now.strftime('%Y-%m-%d_%H%M%S')}",
        "sentiment": sentiment,
        "total": len(results),
        "resolved": resolved,
        "errors": errors,
        "total_tokens": total_tokens,
        "results": results,
    }

    out_dir = Path(f"/results/runs/{summary['run_id']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sentiment_summary.json").write_text(json.dumps(summary, indent=2))
    results_volume.commit()

    print(f"\n{'='*60}")
    print(f"SENTIMENT INJECTION — {sentiment.upper()}")
    print(f"  Resolved: {resolved}/{len(results)}")
    print(f"  Errors:   {errors}")
    print(f"  Tokens:   {total_tokens:,}")
    print(f"{'='*60}")

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@app.local_entrypoint()
def main(count: int = 10, seed: Optional[int] = None, sentiment: Optional[str] = None):
    """Run research eval from the command line.

    --sentiment frustrated|disengaged|neutral|skeptical  → inject forced-sentiment traces
    --count 0  → debug tracing
    """
    if count == 0 and not sentiment:
        result = debug_tracing.remote()
        print(result)
        return

    if sentiment:
        valid = ["frustrated", "disengaged", "neutral", "skeptical"]
        if sentiment not in valid:
            print(f"Invalid sentiment '{sentiment}'. Choose from: {valid}")
            return
        summary = run_sentiment_batch.remote(sentiment=sentiment, count=count, seed=seed)
        print(f"\nSentiment injection ({sentiment}): {summary['resolved']}/{summary['total']} resolved")
        print(f"Total tokens: {summary['total_tokens']:,}")
        return

    summary = run_batch.remote(count=count, seed=seed)
    print(f"\nResearch eval: {summary['resolved']}/{summary['total']} resolved")
    print(f"Total tokens: {summary['total_tokens']:,}")
