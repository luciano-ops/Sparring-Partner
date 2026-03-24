I need you to deploy my **health agent** app to Modal, following the exact same pattern as my deep-research-agent deployment that's already working. I'll give you all the reference code and context so you can do this without any additional info from me.

## Environment & Auth

- **Modal environment**: `internal-agents-l`
- **Modal CLI path**: `/Users/lucianoarroyo/Library/Python/3.9/bin/modal`
- **Modal auth**: Already configured at `~/.modal.toml` for `judgmentlabs` workspace
- **To run commands**: `MODAL_ENVIRONMENT=internal-agents-l /Users/lucianoarroyo/Library/Python/3.9/bin/modal <command>`
- **The health agent app lives at**: `/Users/lucianoarroyo/test/health-agent/` (create this directory if it doesn't exist)

## Available Modal Secrets (in `internal-agents-l` environment)

These are the secret names as they appear in the Modal dashboard:
- `Health-Agent-Anthropic-Key` — **USE THIS ONE** (not the Research or Legal ones)
- `Gemini-key`
- `JudgmentAPI_Key`
- `judgment-org-id`

**CRITICAL: Environment Variable Remapping**
Modal converts secret key names to env vars by replacing dashes with underscores. So:
- `Health-Agent-Anthropic-Key` → exposes env var `Health_Agent_Anthropic_Key` (NOT `ANTHROPIC_API_KEY`)
- `Gemini-key` → exposes `Gemini_key` (NOT `GEMINI_API_KEY`)
- `JudgmentAPI_Key` → exposes `Judgment_API_Key` (NOT `JUDGMENT_API_KEY`)
- `judgment-org-id` → exposes `Judgment_internal_agent_org_id` (NOT `JUDGMENT_ORG_ID`)

You MUST add a `_ensure_env_vars()` function that remaps these to the canonical names the code expects (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `JUDGMENT_API_KEY`, `JUDGMENT_ORG_ID`), and call it at the top of every Modal worker function.

## Known Gotchas (learned the hard way)

1. **`packaging` dependency**: `judgeval` internally imports `packaging` but doesn't declare it as a pip dependency. You MUST add `"packaging"` to the `pip_install` list in the Modal image or the tracer will fail with a misleading `ModuleNotFoundError`.

2. **`tracing.py` error handling**: The import of `judgeval` and the call to `jclient.tracer.create()` must be in SEPARATE try/except blocks. Otherwise `ModuleNotFoundError` from `packaging` gets caught by the `ImportError` branch and prints "judgeval not installed" which is wrong.

3. **Python version**: Use `python_version="3.11"` in the Modal image. Don't use `int | None` syntax in the modal deployment file — use `from __future__ import annotations` and `Optional[int]` to be safe.

4. **`Function.map` deprecation**: Add `wrap_returned_exceptions=False` alongside `return_exceptions=True` to avoid deprecation warnings.

5. **Modal Cron async**: If the cron function calls `run_batch.remote()`, there may be an async generator cleanup warning. This is a Modal internal issue and doesn't affect functionality.

6. **Volume commits**: Always call `results_volume.commit()` after writing to the volume, otherwise data may not persist.

## Judgment SDK Tracing Pattern

The tracing module provides lazy init so it's a no-op when credentials are missing. Project name for this health agent should be `"Internal-Health-Agent"`.

## What to Build

Create a `modal_health.py` (the main Modal deployment file) plus the supporting app files. The health agent should follow the EXACT same architecture as the deep-research-agent:

- **Multi-agent system**: Claude Sonnet (`claude-sonnet-4-20250514`) for the main health agent, Gemini Flash (`gemini-2.0-flash`) for the requester simulator, Claude Haiku (`claude-haiku-4-5-20251001`) for simulated tools
- **CycleDeck**: Card-deck distribution class guaranteeing proportional coverage across categories per cycle, with disk persistence via Modal volumes
- **Cron scheduling**: Every 10 minutes via `modal.Cron("*/10 * * * *")`, with 14-day linear traffic ramp and time-of-day awareness
- **Tracing**: Judgment SDK integration via `tracing.py`
- **Fan-out**: `run_single` worker per session, `run_batch` orchestrator using `.map()`

### But adapted for HEALTH domain:

**Health Research Domains** (replace the deep-research domains):
- Clinical Medicine
- Pharmaceuticals/Drug Development
- Public Health/Epidemiology
- Mental Health
- Medical Devices/Digital Health
- Genomics/Precision Medicine

**Health Requester Personas** (replace the research personas):
- Physician/Clinician
- Hospital Administrator
- Pharmaceutical Researcher
- Public Health Official
- Patient Advocate
- Medical Student

**Health Research Types** (replace the research types):
- Clinical Evidence Review
- Drug Interaction Analysis
- Epidemiological Assessment
- Treatment Protocol Comparison
- Regulatory/FDA Analysis
- Health Policy Evaluation

**Health Tools** (replace the research tools):
- `search_medical_literature` — search medical databases (PubMed, Cochrane, etc.)
- `read_clinical_study` — read and extract from clinical studies/trials
- `find_treatment_guidelines` — find relevant clinical practice guidelines
- `check_drug_interactions` — verify drug interactions and contraindications
- `analyze_clinical_data` — analyze clinical/epidemiological datasets
- `draft_clinical_section` — draft a section of a clinical report/summary

**Domain Queries**: Create 15 queries per health domain (90 total), similar depth/variety as the research agent queries.

**System Prompt for the Health Agent**: Adapt to be a senior health/medical research analyst. Method: Search medical literature, analyze clinical evidence, cross-reference treatment guidelines. Output: Cite all studies and guidelines. Final reports: Executive Summary, Clinical Evidence, Treatment Recommendations, Risk-Benefit Analysis, Limitations, Sources.

## REFERENCE CODE — Deep Research Agent (working deployment)

Here is every file from the working deep-research-agent deployment. Use these as your template — adapt the domain/tools/queries but keep the exact same architecture, Modal patterns, and tracing integration.

### `modal_research.py` — Main Modal deployment file
```python
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

    # Set session ID for tracing
    os.environ["JUDGMENT_SESSION_ID"] = f"modal-{profile_id}-{_uuid.uuid4().hex[:8]}"

    from models import QueryProfile
    from agent import ResearchAgent
    from tracing import flush_and_shutdown

    # Build profile
    profile = generate_profile(profile_id, domain, persona, research_type)

    # Run session
    start = time.time()
    try:
        agent = ResearchAgent(profile=profile, verbose=False)
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
    schedule=modal.Cron("*/10 * * * *"),  # every 10 minutes
    timeout=14400,
)
def cron_research():
    """Scheduled research eval — trickle traffic at ~10 runs/hour."""
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo

    PT = ZoneInfo("America/Los_Angeles")
    now_pt = datetime.now(PT)
    hour = now_pt.hour
    is_weekend = now_pt.weekday() >= 5

    # --- Ramp: linear growth over RAMP_DAYS, then plateau ---
    LAUNCH_DATE = "2026-03-13"
    RAMP_DAYS = 14
    launch = datetime.strptime(LAUNCH_DATE, "%Y-%m-%d").replace(tzinfo=PT)
    days_elapsed = (now_pt - launch).total_seconds() / 86400
    ramp = min(1.0, max(0.0, days_elapsed / RAMP_DAYS))

    # --- Full-production traffic ranges (at ramp=1.0) ---
    # ~10/hr during business hours = ~2 per 10-min invocation
    if is_weekend:
        base_count = random.randint(1, 2) if 9 <= hour < 22 else 0
    elif 9 <= hour < 18:  # business hours
        base_count = random.randint(1, 3)  # ~6-18/hr
    elif 18 <= hour < 22:  # evening
        base_count = random.randint(1, 2)  # ~6-12/hr
    else:  # late night / early morning
        base_count = random.randint(0, 1)  # ~0-6/hr

    count = max(1, round(base_count * ramp)) if base_count > 0 else 0

    if count == 0:
        print(f"[cron] {now_pt.isoformat()} — skipping (off-hours)")
        return {"skipped": True}

    seed = int(time.time() * 1000) & 0x7FFFFFFF

    print(f"[cron] {now_pt.isoformat()} — {count} sessions (ramp={ramp:.0%}), seed={seed}")
    return run_batch.remote(count=count, seed=seed)


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
# Entry point
# ---------------------------------------------------------------------------

@app.local_entrypoint()
def main(count: int = 10, seed: Optional[int] = None):
    """Run research eval from the command line."""
    if count == 0:
        # Debug mode: run tracing diagnostic
        result = debug_tracing.remote()
        print(result)
        return
    summary = run_batch.remote(count=count, seed=seed)
    print(f"\nResearch eval: {summary['resolved']}/{summary['total']} resolved")
    print(f"Total tokens: {summary['total_tokens']:,}")
```

### `tracing.py` — Judgment SDK tracing (lazy, no-op when disabled)
```python
"""Judgment SDK tracing — optional, no-op when credentials are missing.

Provides:
  - get_tracer()   → returns the Judgeval tracer (or None)
  - observe()      → lazy decorator forwarding to tracer.observe()
  - wrap_client()  → auto-instrument an LLM client via tracer.wrap()
  - flush_and_shutdown() → flush buffered spans and shut down the tracer

Tracing activates when JUDGMENT_API_KEY is set and `judgeval` is installed.
Otherwise every helper is a silent no-op so the rest of the codebase runs
unchanged.
"""

import atexit
import functools
import os

_tracer = None
_initialized = False


def _ensure_init():
    """Initialize on first access."""
    global _tracer, _initialized
    if _initialized:
        return
    _initialized = True

    api_key = os.environ.get("JUDGMENT_API_KEY")
    if not api_key:
        return

    try:
        from judgeval import Judgeval
    except ImportError:
        print("[tracing] judgeval package not installed — tracing disabled")
        return

    try:
        jclient = Judgeval(project_name="Internal-Deep-Research-Agent")
        _tracer = jclient.tracer.create()

        # Register automatic flush on process exit so CLI runs never lose traces
        atexit.register(_atexit_flush)
    except Exception as exc:
        print(f"[tracing] Judgment SDK init failed: {type(exc).__name__}: {exc}")


def _atexit_flush():
    """Best-effort flush when the process exits."""
    if _tracer is not None:
        try:
            _tracer.force_flush(timeout_millis=10_000)
            _tracer.shutdown(timeout_millis=5_000)
        except Exception:
            pass


def get_tracer():
    """Return the active tracer, or None if tracing is disabled."""
    _ensure_init()
    return _tracer


def flush():
    """Flush all buffered spans without killing the tracer.

    Use this between runs in a long-lived process (e.g. Streamlit) so the
    tracer stays alive for the next run.
    """
    if _tracer is None:
        return
    try:
        _tracer.force_flush(timeout_millis=15_000)
    except Exception as exc:
        print(f"[tracing] flush error: {exc}")


def flush_and_shutdown():
    """Flush all buffered spans and shut down the tracer.

    Only call this when the process is about to exit (CLI mode).
    For long-lived processes like Streamlit, use flush() instead.
    """
    if _tracer is None:
        return
    try:
        _tracer.force_flush(timeout_millis=15_000)
        _tracer.shutdown(timeout_millis=5_000)
    except Exception as exc:
        print(f"[tracing] flush/shutdown error: {exc}")


# ---------------------------------------------------------------------------
# Lazy decorator
# ---------------------------------------------------------------------------

def observe(span_type: str = "function"):
    """Decorator that forwards to ``tracer.observe()`` when available.

    Resolution is *lazy* — the tracer is looked up on the first call, not at
    decoration time, so module-level decorators work even before env vars or
    the ``judgeval`` package are ready.
    """

    def decorator(func):
        _cache: dict = {}  # mutable container → caches the observed fn

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if "fn" not in _cache:
                t = get_tracer()
                _cache["fn"] = (
                    t.observe(span_type=span_type)(func) if t else None
                )
            observed = _cache["fn"]
            if observed is not None:
                return observed(*args, **kwargs)
            return func(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Client auto-instrumentation
# ---------------------------------------------------------------------------

def wrap_client(client_instance):
    """Try to auto-instrument an LLM client via ``tracer.wrap()``.

    Returns the wrapped client on success, or the original on failure /
    when tracing is disabled.
    """
    _ensure_init()
    t = _tracer
    if t is None:
        return client_instance
    try:
        return t.wrap(client_instance)
    except Exception:
        # wrap() may not support this client type — fall back silently
        return client_instance
```

### `agent.py` — Core agent (Claude Sonnet with tool use)
```python
"""Core research agent using Claude with tool use."""

import json
import time

import anthropic

from models import (
    QueryProfile,
    ToolCall,
    ConversationTurn,
    ResearchTrace,
)
from requester_simulator import RequesterSimulator
from tools import (
    web_search,
    read_source,
    find_academic_papers,
    check_facts,
    analyze_data,
    synthesize_section,
    token_tracker,
)
import tools as _tools_module
from tracing import observe, get_tracer, wrap_client

client = wrap_client(anthropic.Anthropic())
AGENT_MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """Senior research analyst. Conduct thorough, accurate research with full source attribution.

METHOD: Search broadly, drill into authoritative sources, cross-reference claims across multiple sources. Assess credibility. Distinguish facts from opinion. Flag contradictions and knowledge gaps.

OUTPUT: Cite all claims. Include confidence levels. Final reports: Executive Summary, Findings, Methodology, Limitations, Sources. Match depth to requester expertise.

TOOLS: Max 3-4 calls per response. Prefer targeted search + read_source over many broad searches. Iterate across turns — search in one turn, read/verify in the next.

Keep responses focused and substantive. No filler."""

TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": "Search the web. Returns titles, URLs, snippets, credibility scores.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "search_type": {
                    "type": "string",
                    "enum": ["general", "academic", "news", "technical"],
                },
            },
            "required": ["query", "search_type"],
        },
    },
    {
        "name": "read_source",
        "description": "Extract structured content from a URL. Returns summary, key findings, credibility, biases.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to read"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "find_academic_papers",
        "description": "Search academic papers. Returns authors, journal, abstract, citations, conclusions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "field": {"type": "string", "description": "Academic field"},
            },
            "required": ["query", "field"],
        },
    },
    {
        "name": "check_facts",
        "description": "Fact-check a claim. Returns verification status, confidence, evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "Claim to verify"},
                "context": {"type": "string", "description": "Claim context"},
            },
            "required": ["claim", "context"],
        },
    },
    {
        "name": "analyze_data",
        "description": "Analyze a dataset. Returns findings, statistics, confidence intervals.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_description": {"type": "string", "description": "Dataset description"},
                "analysis_type": {
                    "type": "string",
                    "enum": ["trend", "comparison", "statistical", "correlation"],
                },
            },
            "required": ["dataset_description", "analysis_type"],
        },
    },
    {
        "name": "synthesize_section",
        "description": "Draft a report section from multiple sources.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Section heading"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Source summaries to synthesize",
                },
                "format": {
                    "type": "string",
                    "enum": ["executive_summary", "detailed_analysis", "bullet_points", "narrative"],
                },
            },
            "required": ["topic", "sources", "format"],
        },
    },
]


# Per-tool truncation limits (chars) for results sent back to Claude.
# Compact tools get tight limits; data-rich tools get more room.
TOOL_RESULT_LIMITS = {
    "web_search": 1500,         # 4-5 search results — titles+snippets
    "read_source": 1200,        # single doc summary + findings
    "find_academic_papers": 1500, # 3-4 papers — titles+abstracts
    "check_facts": 800,         # single verdict + evidence
    "analyze_data": 800,        # stats + findings
    "synthesize_section": 1500, # drafted text
}
DEFAULT_RESULT_LIMIT = 1200


@observe(span_type="tool")
def execute_tool(name: str, inputs: dict) -> str:
    """Execute a research tool and return serialized result."""
    if name == "web_search":
        results = web_search(inputs["query"], inputs["search_type"])
        return json.dumps([r.model_dump() for r in results])
    elif name == "read_source":
        result = read_source(inputs["url"])
        return result.model_dump_json()
    elif name == "find_academic_papers":
        results = find_academic_papers(inputs["query"], inputs["field"])
        return json.dumps([r.model_dump() for r in results])
    elif name == "check_facts":
        result = check_facts(inputs["claim"], inputs["context"])
        return result.model_dump_json()
    elif name == "analyze_data":
        result = analyze_data(
            inputs["dataset_description"], inputs["analysis_type"]
        )
        return result.model_dump_json()
    elif name == "synthesize_section":
        return synthesize_section(
            inputs["topic"], inputs["sources"], inputs["format"]
        )
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


class ResearchAgent:
    """Runs a full deep research session."""

    def __init__(self, profile: QueryProfile, verbose: bool = False):
        self.profile = profile
        self.verbose = verbose
        self.messages: list[dict] = []
        self.all_tool_calls: list[ToolCall] = []
        self.agent_tokens = 0
        self.max_conversation_turns = 6  # max requester-agent exchange pairs
        self.max_tool_rounds = 3  # max tool-use rounds per single agent turn
        self._tools_disabled_logged = False

    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    def _trim_old_context(self):
        """Trim tool results in older messages to reduce context growth."""
        if len(self.messages) <= 4:
            return
        trim_boundary = len(self.messages) - 4
        for i in range(trim_boundary):
            msg = self.messages[i]
            content = msg.get("content")
            if content is None:
                continue
            if msg.get("role") == "user" and isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        c = item.get("content", "")
                        if isinstance(c, str) and len(c) > 300:
                            item["content"] = c[:300] + "...[trimmed]"
            elif msg.get("role") == "assistant" and isinstance(content, str):
                if len(content) > 800:
                    self.messages[i]["content"] = content[:800] + "...[trimmed]"

    @observe(span_type="function")
    def _run_agent_turn(self, user_message: str) -> tuple[str, list[ToolCall]]:
        """Run one agent turn: add user message, call Claude, handle tool loops."""
        self.messages.append({"role": "user", "content": user_message})
        turn_tool_calls = []
        tool_rounds = 0

        use_tools = not _tools_module.tools_degraded
        if not use_tools and not self._tools_disabled_logged:
            self._log("  [Agent] Tools disabled — responding from own knowledge")
            self._tools_disabled_logged = True

        while tool_rounds < self.max_tool_rounds:
            self._trim_old_context()
            call_kwargs = dict(
                model=AGENT_MODEL,
                max_tokens=3000,
                system=SYSTEM_PROMPT,
                messages=self.messages,
            )
            if use_tools:
                call_kwargs["tools"] = TOOL_DEFINITIONS

            response = client.messages.create(**call_kwargs)
            self.agent_tokens += response.usage.input_tokens + response.usage.output_tokens

            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                text_parts = []
                for block in response.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                return "\n".join(text_parts), turn_tool_calls

            MAX_PARALLEL_TOOLS = 4
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            executed = tool_use_blocks[:MAX_PARALLEL_TOOLS]
            skipped = tool_use_blocks[MAX_PARALLEL_TOOLS:]

            if skipped:
                self._log(f"  [Cap] Executing {len(executed)}/{len(tool_use_blocks)} tool calls (skipped {len(skipped)})")

            tool_results = []
            for block in executed:
                self._log(f"  [Tool] {block.name}({json.dumps(block.input)[:80]}...)")
                start = time.time()
                tokens_before = token_tracker.total

                result_str = execute_tool(block.name, block.input)
                limit = TOOL_RESULT_LIMITS.get(block.name, DEFAULT_RESULT_LIMIT)
                result_for_claude = result_str[:limit] if len(result_str) > limit else result_str

                duration = time.time() - start
                tokens_used = token_tracker.total - tokens_before

                tc = ToolCall(
                    tool_name=block.name,
                    inputs=block.input,
                    output=result_str[:500],
                    duration=duration,
                    tokens_used=tokens_used,
                )
                turn_tool_calls.append(tc)
                self.all_tool_calls.append(tc)

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_for_claude,
                    }
                )

            for block in skipped:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": '{"note": "Tool call skipped — limit of 4 parallel calls reached. Re-request if needed."}',
                    }
                )

            if not tool_results:
                break

            self.messages.append({"role": "user", "content": tool_results})
            tool_rounds += 1

        for msg in reversed(self.messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", [])
                if isinstance(content, str):
                    return content or "I've completed my research on this topic.", turn_tool_calls
                text_parts = []
                for block in content:
                    text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
                    if text:
                        text_parts.append(text)
                if text_parts:
                    return "\n".join(text_parts), turn_tool_calls
                break
        return "I've completed my research on this topic.", turn_tool_calls

    @observe(span_type="function")
    def run_session(self) -> ResearchTrace:
        """Run a full research session and return the trace."""
        start_time = time.time()
        token_tracker.reset()
        _tools_module.tools_degraded = False
        _tools_module._haiku_consecutive_failures = 0
        turns: list[ConversationTurn] = []

        tracer = get_tracer()
        if tracer:
            tracer.set_session_id(self.profile.id)
            tracer.set_input(self.profile.query)
            tracer.set_attributes({
                "profile_id": self.profile.id,
                "research_type": self.profile.research_type.value,
                "domain": self.profile.domain,
                "complexity": self.profile.complexity.value,
                "requester_persona": self.profile.requester_persona.value,
                "depth_preference": self.profile.depth_preference.value,
                "time_sensitivity": self.profile.time_sensitivity.value,
            })

        self._log(f"\n{'='*60}")
        self._log(f"Research Session: {self.profile.query[:80]}")
        self._log(f"Type: {self.profile.research_type.value} | Domain: {self.profile.domain}")
        self._log(f"Persona: {self.profile.requester_persona.value} | Complexity: {self.profile.complexity.value}")
        self._log(f"{'='*60}")

        requester = RequesterSimulator(self.profile)
        self._log(f"Behavioral arc: {requester.arc}")

        self._log(f"\n--- Turn 1: Requester ---")
        initial_msg = requester.get_initial_message()
        self._log(f"Requester: {initial_msg[:200]}...")

        turns.append(
            ConversationTurn(
                turn_number=1,
                role="requester",
                content=initial_msg,
                timestamp=time.time(),
            )
        )

        turn_num = 2
        current_requester_msg = initial_msg
        last_agent_response = ""

        while turn_num <= self.max_conversation_turns * 2 and not requester.is_done:
            self._log(f"\n--- Turn {turn_num}: Agent researching ---")
            agent_response, turn_tools = self._run_agent_turn(current_requester_msg)
            self._log(f"Agent: {agent_response[:200]}...")
            if turn_tools:
                self._log(f"  ({len(turn_tools)} tool calls)")

            turns.append(
                ConversationTurn(
                    turn_number=turn_num,
                    role="agent",
                    content=agent_response,
                    tool_calls=turn_tools,
                    timestamp=time.time(),
                )
            )
            last_agent_response = agent_response
            turn_num += 1

            if requester.is_done:
                break

            self._log(f"\n--- Turn {turn_num}: Requester ---")
            requester_msg = requester.respond(agent_response)
            self._log(f"Requester: {requester_msg[:200]}...")

            turns.append(
                ConversationTurn(
                    turn_number=turn_num,
                    role="requester",
                    content=requester_msg,
                    timestamp=time.time(),
                )
            )

            if requester.is_done:
                self._log("  [Requester satisfied — ending conversation]")
                break

            current_requester_msg = requester_msg
            turn_num += 1

        self._log(f"\n--- Final Report ---")
        final_prompt = (
            "Produce your final report: Executive Summary, Findings, "
            "Methodology, Limitations, Sources. Cite all sources."
        )
        try:
            final_report, final_tools = self._run_agent_turn(final_prompt)
        except Exception as e:
            self._log(f"  Final report generation failed ({e}), using last agent response")
            final_report = last_agent_response
            final_tools = []
        self._log(f"Final report length: {len(final_report)} chars")

        turns.append(
            ConversationTurn(
                turn_number=turn_num,
                role="agent",
                content=final_report,
                tool_calls=final_tools,
                timestamp=time.time(),
            )
        )

        duration = time.time() - start_time
        total_tokens = self.agent_tokens + token_tracker.total

        trace = ResearchTrace(
            profile_id=self.profile.id,
            profile=self.profile,
            turns=turns,
            tool_calls=self.all_tool_calls,
            total_tokens=total_tokens,
            duration=duration,
            final_report=final_report,
        )

        if tracer:
            tracer.set_output(final_report[:3000] if final_report else "")
            tracer.set_attributes({
                "total_turns": len(turns),
                "total_tool_calls": len(self.all_tool_calls),
                "total_tokens": total_tokens,
                "duration_seconds": round(duration, 1),
                "tools_degraded": _tools_module.tools_degraded,
            })

        self._log(f"\n{'='*60}")
        self._log(f"Session complete: {len(turns)} turns, {len(self.all_tool_calls)} tool calls")
        self._log(f"Tokens: {total_tokens:,} | Duration: {duration:.1f}s")
        self._log(f"{'='*60}\n")

        return trace
```

### `tools.py` — Simulated tools (Claude Haiku)
```python
"""Simulated research tools using Claude Haiku for realistic content generation."""

import json
import re

import anthropic

from models import (
    SearchResult,
    SourceDocument,
    PaperResult,
    FactCheckResult,
    DataAnalysis,
)
from tracing import observe, wrap_client

client = None  # lazy init to avoid import-time failures
HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _get_client() -> anthropic.Anthropic:
    """Lazy-init the Anthropic client (auto-instrumented when tracing is on)."""
    global client
    if client is None:
        client = wrap_client(anthropic.Anthropic())
    return client


class TokenTracker:
    """Track token usage across tool calls."""

    def __init__(self):
        self.total_input = 0
        self.total_output = 0

    def add(self, usage):
        self.total_input += usage.input_tokens
        self.total_output += usage.output_tokens

    @property
    def total(self):
        return self.total_input + self.total_output

    def reset(self):
        self.total_input = 0
        self.total_output = 0


token_tracker = TokenTracker()
_haiku_consecutive_failures = 0
tools_degraded = False  # exported flag — agent checks this to disable tools


def _parse_json(text: str):
    """Parse JSON from an LLM response, handling markdown code blocks."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    for pattern in [r"\[.*\]", r"\{.*\}"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Could not parse JSON from response: {text[:300]}")


@observe(span_type="llm")
def _call_haiku(prompt: str, max_tokens: int = 3000) -> str:
    """Call Claude Haiku and track tokens. Raises on failure with a clear message."""
    global _haiku_consecutive_failures, tools_degraded

    if tools_degraded:
        raise RuntimeError("Tools degraded — skipping Haiku call")

    c = _get_client()
    try:
        response = c.messages.create(
            model=HAIKU_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        token_tracker.add(response.usage)
        _haiku_consecutive_failures = 0
        return response.content[0].text
    except Exception as e:
        _haiku_consecutive_failures += 1
        if _haiku_consecutive_failures <= 3:
            print(f"  [tools] Haiku call failed ({type(e).__name__}): {e}")
        if _haiku_consecutive_failures >= 3:
            tools_degraded = True
            print("  [tools] 3 consecutive failures — disabling tool LLM calls for this session")
        raise


@observe(span_type="tool")
def web_search(query: str, search_type: str) -> list[SearchResult]:
    """Simulate a web search returning 3-6 results with mixed credibility."""
    prompt = f"""Generate 4 realistic {search_type} web search results for: "{query}"

JSON array. Each object: "title", "url" (fake but realistic), "snippet" (2 sentences), "source_type" (academic_paper|news_article|government_report|blog|whitepaper|dataset), "credibility_score" (0-1, vary: include <0.5 and >0.8), "published_date" (YYYY-MM-DD, vary dates).

JSON only."""

    try:
        raw = _call_haiku(prompt, max_tokens=1500)
        data = _parse_json(raw)
        return [SearchResult(**item) for item in data]
    except Exception:
        return [
            SearchResult(
                title=f"Search result for: {query}",
                url=f"https://www.example.com/search/{query.replace(' ', '-')}",
                snippet=f"Relevant information about {query}.",
                source_type="news_article",
                credibility_score=0.7,
                published_date="2025-01-15",
            )
        ]


@observe(span_type="tool")
def read_source(url: str) -> SourceDocument:
    """Simulate reading and extracting content from a source URL."""
    prompt = f"""Extract structured content from: {url}

JSON object: "title", "url": "{url}", "source_type" (academic_paper|news_article|government_report|blog|whitepaper|dataset), "publication_date" (YYYY-MM-DD), "credibility_score" (0-1), "summary" (3 sentences), "key_findings" (3 strings), "potential_biases" (1-2 strings).

JSON only."""

    try:
        raw = _call_haiku(prompt, max_tokens=1000)
        data = _parse_json(raw)
        data["url"] = url
        return SourceDocument(**data)
    except Exception:
        return SourceDocument(
            title=f"Document from {url}",
            url=url,
            source_type="news_article",
            publication_date="2025-01-15",
            credibility_score=0.6,
            summary=f"Content extracted from {url}.",
            key_findings=["Finding 1", "Finding 2"],
            potential_biases=["Source bias not assessed"],
        )


@observe(span_type="tool")
def find_academic_papers(query: str, field: str) -> list[PaperResult]:
    """Simulate an academic paper search returning 2-5 papers."""
    prompt = f"""Generate 3 realistic academic papers for "{query}" in {field}.

JSON array. Each: "title", "authors" (2-3 names), "journal", "year" (2018-2025), "abstract" (2 sentences), "citation_count", "key_conclusions" (2 strings), "doi" (10.xxxx/...).

JSON only."""

    try:
        raw = _call_haiku(prompt, max_tokens=1500)
        data = _parse_json(raw)
        return [PaperResult(**item) for item in data]
    except Exception:
        return [
            PaperResult(
                title=f"A Study on {query}",
                authors=["Smith, J.", "Chen, L."],
                journal=f"Journal of {field}",
                year=2024,
                abstract=f"This paper examines {query}.",
                citation_count=12,
                key_conclusions=[f"Key finding related to {query}"],
                doi="10.1234/example.2024.00001",
            )
        ]


@observe(span_type="tool")
def check_facts(claim: str, context: str) -> FactCheckResult:
    """Simulate fact-checking a specific claim."""
    prompt = f"""Fact-check: "{claim}" (context: {context})

JSON object: "claim": "{claim}", "status" (verified|partially_true|unverified|false|disputed), "confidence" (0-1), "supporting_evidence" (2 strings), "contradicting_evidence" (1 string or empty), "sources_checked" (3-8).

JSON only."""

    try:
        raw = _call_haiku(prompt, max_tokens=800)
        data = _parse_json(raw)
        data["claim"] = claim
        return FactCheckResult(**data)
    except Exception:
        return FactCheckResult(
            claim=claim,
            status="unverified",
            confidence=0.5,
            supporting_evidence=["Limited evidence available"],
            contradicting_evidence=[],
            sources_checked=3,
        )


@observe(span_type="tool")
def analyze_data(dataset_description: str, analysis_type: str) -> DataAnalysis:
    """Simulate data analysis on a described dataset."""
    prompt = f"""Analyze dataset: "{dataset_description}" ({analysis_type} analysis)

JSON object: "dataset_description": "{dataset_description}", "analysis_type": "{analysis_type}", "findings" (3 strings), "key_statistics" (3 numeric key-value pairs), "confidence_intervals" (2 string key-value pairs), "chart_description" (1 sentence), "methodology_notes" (1 sentence).

JSON only."""

    try:
        raw = _call_haiku(prompt, max_tokens=800)
        data = _parse_json(raw)
        data["dataset_description"] = dataset_description
        data["analysis_type"] = analysis_type
        return DataAnalysis(**data)
    except Exception:
        return DataAnalysis(
            dataset_description=dataset_description,
            analysis_type=analysis_type,
            findings=[f"Analysis of {dataset_description} shows notable trends."],
            key_statistics={"sample_size": 1000.0, "mean": 50.0},
            confidence_intervals={"primary": "95% CI [45.0, 55.0]"},
            chart_description=f"A {analysis_type} chart showing trends in the data.",
            methodology_notes=f"Standard {analysis_type} analysis applied.",
        )


@observe(span_type="tool")
def synthesize_section(topic: str, sources: list[str], format: str) -> str:
    """Synthesize a research report section from sources."""
    sources_text = "\n".join(f"- {s}" for s in sources[:6])
    prompt = f"""Write a {format} section on "{topic}" using these sources:
{sources_text}

Cite sources as [1], [2], etc. Be substantive and analytical."""

    try:
        return _call_haiku(prompt, max_tokens=1200)
    except Exception:
        return f"Section on {topic}: Further analysis pending."
```

### `models.py` — Pydantic models
```python
"""Pydantic models for the deep research agent."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class ResearchType(str, Enum):
    LITERATURE_REVIEW = "Literature_Review"
    MARKET_ANALYSIS = "Market_Analysis"
    TECHNICAL_DEEP_DIVE = "Technical_Deep_Dive"
    FACT_CHECKING = "Fact_Checking"
    COMPARATIVE_ANALYSIS = "Comparative_Analysis"
    TREND_RESEARCH = "Trend_Research"


class Complexity(str, Enum):
    SIMPLE = "Simple"
    MODERATE = "Moderate"
    COMPLEX = "Complex"
    EXPERT_LEVEL = "Expert_Level"


class TimeSensitivity(str, Enum):
    HISTORICAL = "Historical"
    CURRENT = "Current"
    BREAKING = "Breaking"
    EVERGREEN = "Evergreen"


class RequesterPersona(str, Enum):
    EXECUTIVE = "Executive"
    ACADEMIC = "Academic"
    JOURNALIST = "Journalist"
    STUDENT = "Student"
    ANALYST = "Analyst"
    CURIOUS_GENERALIST = "Curious_Generalist"


class DepthPreference(str, Enum):
    OVERVIEW = "Overview"
    DETAILED = "Detailed"
    EXHAUSTIVE = "Exhaustive"


class QueryProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    research_type: ResearchType
    domain: str
    complexity: Complexity
    query: str
    sub_questions: list[str] = []
    expected_sources: int = 5
    time_sensitivity: TimeSensitivity = TimeSensitivity.CURRENT
    requester_persona: RequesterPersona = RequesterPersona.ANALYST
    depth_preference: DepthPreference = DepthPreference.DETAILED
    edge_case_tags: list[str] = []


# --- Tool result models ---


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    source_type: str
    credibility_score: float
    published_date: str


class SourceDocument(BaseModel):
    title: str
    url: str
    source_type: str
    publication_date: str
    credibility_score: float
    summary: str
    key_findings: list[str]
    potential_biases: list[str]


class PaperResult(BaseModel):
    title: str
    authors: list[str]
    journal: str
    year: int
    abstract: str
    citation_count: int
    key_conclusions: list[str]
    doi: str


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    PARTIALLY_TRUE = "partially_true"
    UNVERIFIED = "unverified"
    FALSE = "false"
    DISPUTED = "disputed"


class FactCheckResult(BaseModel):
    claim: str
    status: VerificationStatus
    confidence: float
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    sources_checked: int


class DataAnalysis(BaseModel):
    dataset_description: str
    analysis_type: str
    findings: list[str]
    key_statistics: dict[str, float]
    confidence_intervals: dict[str, str]
    chart_description: str
    methodology_notes: str


# --- Trace models ---


class ToolCall(BaseModel):
    tool_name: str
    inputs: dict
    output: str
    duration: float
    tokens_used: int


class ConversationTurn(BaseModel):
    turn_number: int
    role: str  # "requester" or "agent"
    content: str
    tool_calls: list[ToolCall] = []
    timestamp: float


class ResearchTrace(BaseModel):
    profile_id: str
    profile: QueryProfile
    turns: list[ConversationTurn] = []
    tool_calls: list[ToolCall] = []
    total_tokens: int = 0
    duration: float = 0.0
    final_report: Optional[str] = None
```

### `requester_simulator.py` — Gemini-powered requester simulator
```python
"""Simulated research requester using Google Gemini."""

import hashlib
import os

from google import genai
from google.genai import types

from models import QueryProfile


BEHAVIORAL_ARCS = ["demanding", "skeptical", "guided", "exploratory"]


def get_behavioral_arc(profile_id: str) -> str:
    """Deterministically assign a behavioral arc via MD5 hash of profile ID."""
    hash_val = int(hashlib.md5(profile_id.encode()).hexdigest(), 16)
    return BEHAVIORAL_ARCS[hash_val % len(BEHAVIORAL_ARCS)]


def build_system_prompt(profile: QueryProfile, arc: str) -> str:
    """Build the system prompt for the requester simulator."""
    arc_instructions = {
        "demanding": (
            "You are demanding and thorough. You want exhaustive answers with maximum depth. "
            "If the researcher gives a surface-level response, push back hard: 'That's too shallow, "
            "I need more depth on X.' Keep asking for more detail, more sources, more nuance. "
            "You are not easily satisfied and expect the highest quality research."
        ),
        "skeptical": (
            "You are deeply skeptical of all claims. Question every source's methodology and credibility. "
            "Ask about potential biases, conflicts of interest, and sample sizes. Say things like "
            "'That source seems biased — do you have independent verification?' and "
            "'What's the methodology behind that claim?' Push the researcher to verify everything."
        ),
        "guided": (
            "You have a specific thesis or hypothesis you want the research to investigate. "
            "You believe the research should support or definitively refute your position. "
            "Guide the researcher toward your angle: 'I think X is actually caused by Y — can you "
            "find evidence for or against that?' Be open to being wrong but push your thesis."
        ),
        "exploratory": (
            "You are curious and open-ended. Follow interesting threads wherever they lead. "
            "Change direction when something unexpected comes up: 'Oh, that's interesting — "
            "can you explore that tangent?' You don't have a fixed goal and enjoy discovering "
            "unexpected connections. Ask broad follow-up questions."
        ),
    }

    persona_style = {
        "Executive": "You speak concisely and care about bottom-line implications and actionable insights. You want clear takeaways.",
        "Academic": "You care about rigor, methodology, peer review, and proper attribution. You use technical language.",
        "Journalist": "You want compelling narratives, key quotes, and newsworthy angles. You ask 'why should people care?'",
        "Student": "You're learning and may ask for explanations of complex concepts. You appreciate clear, structured answers.",
        "Analyst": "You want data-driven insights, trends, and quantitative evidence. You think in frameworks and comparisons.",
        "Curious_Generalist": "You're broadly curious and want accessible explanations. You ask 'how does this connect to X?'",
    }

    return f"""You are simulating a person who has requested deep research on a topic.

YOUR PERSONA: {profile.requester_persona.value}
{persona_style.get(profile.requester_persona.value, "")}

YOUR BEHAVIORAL STYLE: {arc.upper()}
{arc_instructions[arc]}

RESEARCH CONTEXT:
- Main question: {profile.query}
- Research type: {profile.research_type.value}
- Domain: {profile.domain}
- Complexity level: {profile.complexity.value}
- You want {profile.depth_preference.value.lower()}-level depth
- Time sensitivity: {profile.time_sensitivity.value}

SUB-QUESTIONS you may want to ask as follow-ups (use these progressively):
{chr(10).join(f'- {q}' for q in profile.sub_questions)}

CONVERSATION RULES:
1. Start by stating your research question clearly and what you need it for.
2. After the researcher responds, react naturally:
   - If the response is good, acknowledge it and ask a follow-up from your sub-questions.
   - If it's shallow, push for more depth.
   - If you see something surprising, react ("That contradicts what I expected").
   - If you want a specific format, ask for it ("Can you summarize that as bullet points?").
3. After 6-8 exchanges, begin wrapping up. Ask for a final structured report.
4. On your final message, thank the researcher and indicate you're satisfied (or note remaining gaps).

IMPORTANT: Stay in character. You are the REQUESTER, not the researcher. Ask questions, provide direction, react to findings — but don't do the research yourself. Keep messages concise (2-4 sentences typically)."""


_SATISFACTION_SIGNALS = [
    "i'm satisfied",
    "i am satisfied",
    "that's all",
    "that is all",
    "no further questions",
    "don't have any further",
    "no more questions",
    "that concludes",
    "this concludes",
    "nothing else",
    "i'm done",
    "that's everything",
]


class RequesterSimulator:
    """Simulates a research requester using Gemini."""

    def __init__(self, profile: QueryProfile):
        self.profile = profile
        self.arc = get_behavioral_arc(profile.id)
        self.turn_count = 0
        self.max_turns = 6  # 6 requester messages = ~12 total turns
        self._satisfied = False

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        self.client = genai.Client(api_key=api_key)
        system_prompt = build_system_prompt(profile, self.arc)

        self.chat = self.client.chats.create(
            model="gemini-2.0-flash",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.8,
            ),
        )

    def get_initial_message(self) -> str:
        """Get the requester's opening research query."""
        self.turn_count += 1
        prompt = (
            "Start the conversation by stating your research question and what you need. "
            "Be specific about what kind of research output you're looking for."
        )
        response = self.chat.send_message(prompt)
        return response.text

    def respond(self, agent_message: str) -> str:
        """React to the agent's response and provide next direction."""
        self.turn_count += 1

        if self.turn_count >= self.max_turns:
            prompt = (
                f"The researcher said:\n\n{agent_message}\n\n"
                "This is your FINAL message. Wrap up the conversation: thank the researcher, "
                "note if there are any remaining gaps, and ask for the final structured report "
                "if you haven't already. Indicate clearly that you're satisfied and done."
            )
        elif self.turn_count >= self.max_turns - 1:
            prompt = (
                f"The researcher said:\n\n{agent_message}\n\n"
                "You're nearing the end of this research session. Start wrapping up — "
                "ask any final questions or request the final structured report."
            )
        else:
            prompt = (
                f"The researcher said:\n\n{agent_message}\n\n"
                "React naturally and provide your next direction or follow-up question."
            )

        response = self.chat.send_message(prompt)
        text = response.text

        # Detect satisfaction in the response
        lower = text.lower()
        if any(signal in lower for signal in _SATISFACTION_SIGNALS):
            self._satisfied = True

        return text

    @property
    def is_done(self) -> bool:
        return self._satisfied or self.turn_count >= self.max_turns
```

### `run.py` — CLI entrypoint (for local testing)
```python
"""CLI runner for the deep research agent."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from models import QueryProfile, ResearchType, Complexity, TimeSensitivity, RequesterPersona, DepthPreference
from agent import ResearchAgent
from tracing import flush_and_shutdown


def generate_random_profile() -> QueryProfile:
    """Generate a random research profile for testing."""
    import random
    return QueryProfile(
        research_type=random.choice(list(ResearchType)),
        domain=random.choice(["AI/ML", "Finance", "Healthcare", "Climate", "Geopolitics", "Cybersecurity"]),
        complexity=random.choice(list(Complexity)),
        query=random.choice([
            "What are the latest advances in large language model reasoning?",
            "Analyze the impact of central bank digital currencies on banking",
            "Compare CRISPR gene therapy approaches for sickle cell disease",
            "Evaluate carbon capture technologies deployed at scale",
            "Analyze semiconductor supply chain geopolitics",
            "Compare post-quantum cryptography standards and migration timelines",
        ]),
        time_sensitivity=random.choice(list(TimeSensitivity)),
        requester_persona=random.choice(list(RequesterPersona)),
        depth_preference=random.choice(list(DepthPreference)),
    )


def run_single(profile: QueryProfile, verbose: bool = False) -> dict:
    """Run a single research session."""
    agent = ResearchAgent(profile=profile, verbose=verbose)
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
    parser = argparse.ArgumentParser(description="Run deep research agent")
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
```

### `requirements.txt`
```
anthropic>=0.39.0
pydantic>=2.0.0
google-genai>=1.0.0
tqdm>=4.60.0
judgeval>=0.1.0
```

## Your Task

1. Create the directory `/Users/lucianoarroyo/test/health-agent/` if it doesn't exist
2. Create ALL the adapted files for the health agent:
   - `modal_health.py` — adapted Modal deployment (app name: `"health-agent-eval"`, volume: `"health-results"`, secrets use `Health-Agent-Anthropic-Key` instead of `Research-Agent-Anthropic-Key`, env alias maps `Health_Agent_Anthropic_Key` → `ANTHROPIC_API_KEY`, project name `"Internal-Health-Agent"`, LAUNCH_DATE should be today's date)
   - `agent.py` — adapted for health domain (system prompt, tool definitions, tool names)
   - `tools.py` — adapted health tools (search_medical_literature, read_clinical_study, find_treatment_guidelines, check_drug_interactions, analyze_clinical_data, draft_clinical_section)
   - `models.py` — adapted enums and models for health domain
   - `requester_simulator.py` — adapted persona styles for health personas
   - `tracing.py` — COPY EXACTLY from reference (only change project name to `"Internal-Health-Agent"`)
   - `run.py` — adapted for health domain
   - `requirements.txt` — same as reference
3. Deploy to Modal: `MODAL_ENVIRONMENT=internal-agents-l /Users/lucianoarroyo/Library/Python/3.9/bin/modal deploy modal_health.py`
4. Run a quick test: `MODAL_ENVIRONMENT=internal-agents-l /Users/lucianoarroyo/Library/Python/3.9/bin/modal run modal_health.py --count 0` (debug tracing)
5. If tracing works, run a real test: `MODAL_ENVIRONMENT=internal-agents-l /Users/lucianoarroyo/Library/Python/3.9/bin/modal run modal_health.py --count 1`
6. Show me the results

Do NOT ask me any questions. Just build it, deploy it, and show me results.
