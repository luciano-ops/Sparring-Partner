"""Modal app for health research agent — synthetic evaluation sandbox.

Usage:
    # Deploy to internal-agents-l environment
    modal deploy modal_health.py --env internal-agents-l

    # Run from CLI (default: 10 tasks)
    modal run modal_health.py --env internal-agents-l

    # Run with custom count
    modal run modal_health.py --env internal-agents-l --count 20

    # Debug: test tracing inside the container
    modal run modal_health.py --env internal-agents-l --count 0

    # Shell into the container
    modal shell modal_health.py --env internal-agents-l
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

app = modal.App("health-agent-eval")

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

results_volume = modal.Volume.from_name("health-results", create_if_missing=True)

# NOTE: Modal secrets expose env vars based on the key names used when creating
# the secret in the Modal dashboard.  If the secret key doesn't exactly match
# what the code expects (ANTHROPIC_API_KEY, GEMINI_API_KEY, etc.), we remap in
# _ensure_env_vars() at the top of each worker.
secrets = [
    modal.Secret.from_name("Health-Agent-Anthropic-Key"),
    modal.Secret.from_name("Gemini-key"),
    modal.Secret.from_name("JudgmentAPI_Key"),
    modal.Secret.from_name("judgment-org-id"),
]

# Mapping: (expected_env_var) -> list of actual names exposed by Modal secrets
# Modal converts secret names to env vars with underscores (dashes -> underscores)
_ENV_ALIASES = {
    "ANTHROPIC_API_KEY": [
        "ANTHROPIC_API_KEY",
        "Health_Agent_Anthropic_Key",
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
# Category definitions & queries (health domain)
# ---------------------------------------------------------------------------

HEALTH_DOMAINS = [
    "Cardiac", "Endocrine", "GI", "Mental Health", "Neurological", "Respiratory",
]

REQUESTER_PERSONAS = [
    "Physician", "Hospital_Administrator", "Pharmaceutical_Researcher",
    "Public_Health_Official", "Patient_Advocate", "Medical_Student",
]

RESEARCH_TYPES = [
    "Clinical_Evidence_Review", "Drug_Interaction_Analysis",
    "Epidemiological_Assessment", "Treatment_Protocol_Comparison",
    "Regulatory_FDA_Analysis", "Health_Policy_Evaluation",
]

# Default even weights
DEFAULT_DOMAIN_WEIGHTS = {d: 1.0 for d in HEALTH_DOMAINS}
DEFAULT_PERSONA_WEIGHTS = {p: 1.0 for p in REQUESTER_PERSONAS}
DEFAULT_TYPE_WEIGHTS = {t: 1.0 for t in RESEARCH_TYPES}

# Session depth tiers — map (complexity, depth_preference) to
# (max_conversation_turns, max_tool_rounds) for trace length variety.
SESSION_DEPTH = {
    ("Simple", "Overview"):         (2, 1),   # quick lookup
    ("Simple", "Detailed"):         (2, 2),   # short but thorough tools
    ("Simple", "Exhaustive"):       (3, 2),
    ("Moderate", "Overview"):       (2, 2),   # quick moderate
    ("Moderate", "Detailed"):       (3, 2),
    ("Moderate", "Exhaustive"):     (4, 3),
    ("Complex", "Overview"):        (3, 2),
    ("Complex", "Detailed"):        (5, 3),
    ("Complex", "Exhaustive"):      (6, 3),
    ("Expert_Level", "Overview"):   (4, 3),
    ("Expert_Level", "Detailed"):   (6, 3),
    ("Expert_Level", "Exhaustive"): (8, 3),
}

DOMAIN_QUERIES = {
    "Cardiac": [
        "What are the latest guidelines for managing atrial fibrillation with direct oral anticoagulants?",
        "Compare outcomes of TAVR vs surgical aortic valve replacement in intermediate-risk patients",
        "Analyze the evidence for SGLT2 inhibitors in heart failure with preserved ejection fraction",
        "What is the current evidence on catheter ablation vs antiarrhythmic drugs for paroxysmal AF?",
        "Evaluate the role of cardiac MRI in diagnosing myocarditis post-viral infection",
        "What are the latest clinical trial results for PCSK9 inhibitors in familial hypercholesterolemia?",
        "Compare dual antiplatelet therapy durations after drug-eluting stent implantation",
        "Analyze the evidence for renal denervation in treatment-resistant hypertension",
        "What is the state of research on titin-truncating variants in dilated cardiomyopathy?",
        "Evaluate remote monitoring outcomes for patients with implantable cardiac devices",
        "What are the risk stratification tools for sudden cardiac death in hypertrophic cardiomyopathy?",
        "Compare the efficacy of different beta-blockers in post-MI patients with reduced EF",
        "Analyze the evidence for colchicine in secondary prevention of cardiovascular events",
        "What is the optimal blood pressure target for elderly patients with coronary artery disease?",
        "Evaluate the role of lipoprotein(a) testing in cardiovascular risk assessment",
    ],
    "Endocrine": [
        "What are the latest advances in closed-loop insulin delivery systems for type 1 diabetes?",
        "Compare GLP-1 receptor agonists for weight management in patients with type 2 diabetes",
        "Analyze the evidence for thyroid cancer overdiagnosis and active surveillance approaches",
        "What is the current evidence on testosterone replacement therapy cardiovascular safety?",
        "Evaluate the role of continuous glucose monitoring in gestational diabetes management",
        "What are the latest clinical trial results for tirzepatide vs semaglutide for obesity?",
        "Compare management strategies for primary hyperaldosteronism detection and treatment",
        "Analyze the evidence for vitamin D supplementation in preventing type 2 diabetes",
        "What is the state of research on beta-cell regeneration therapies for diabetes?",
        "Evaluate adrenal incidentaloma management guidelines and follow-up protocols",
        "What are the risk factors and screening recommendations for MEN syndromes?",
        "Compare the efficacy of different insulin regimens in hospitalized patients with hyperglycemia",
        "Analyze the evidence for metformin use in prediabetes prevention across different populations",
        "What is the optimal approach to managing subclinical hypothyroidism in elderly patients?",
        "Evaluate the role of bariatric surgery in type 2 diabetes remission and long-term outcomes",
    ],
    "GI": [
        "What are the latest advances in fecal microbiota transplantation for recurrent C. difficile?",
        "Compare biologic therapies for moderate-to-severe Crohn's disease first-line treatment",
        "Analyze the evidence for AI-assisted colonoscopy in adenoma detection rate improvement",
        "What is the current evidence on proton pump inhibitor long-term safety concerns?",
        "Evaluate the role of non-invasive liver fibrosis scoring in NAFLD/NASH screening",
        "What are the latest clinical trial results for eosinophilic esophagitis biologics?",
        "Compare management strategies for Barrett's esophagus with low-grade dysplasia",
        "Analyze the evidence for Mediterranean diet in inflammatory bowel disease management",
        "What is the state of research on gut-brain axis therapies for irritable bowel syndrome?",
        "Evaluate pancreatic enzyme replacement therapy optimization in chronic pancreatitis",
        "What are the risk stratification models for hepatocellular carcinoma surveillance?",
        "Compare the efficacy of different antifibrotic agents in NASH-related liver fibrosis",
        "Analyze the evidence for early cholecystectomy vs conservative management in acute cholecystitis",
        "What is the optimal screening strategy for colorectal cancer in average-risk populations?",
        "Evaluate the role of small bowel capsule endoscopy in obscure GI bleeding workup",
    ],
    "Mental Health": [
        "What are the latest advances in ketamine and esketamine for treatment-resistant depression?",
        "Compare SSRI efficacy and tolerability profiles across different anxiety disorder subtypes",
        "Analyze the evidence for psilocybin-assisted therapy in major depressive disorder",
        "What is the current evidence on long-acting injectable antipsychotics vs oral formulations?",
        "Evaluate the role of digital therapeutics and CBT apps in anxiety disorder management",
        "What are the latest clinical trial results for MDMA-assisted therapy for PTSD?",
        "Compare pharmacological approaches to managing treatment-resistant schizophrenia",
        "Analyze the evidence for transcranial magnetic stimulation in obsessive-compulsive disorder",
        "What is the state of research on neuroinflammation biomarkers in bipolar disorder?",
        "Evaluate integrated care models for co-occurring substance use and mental health disorders",
        "What are the risk assessment tools for adolescent suicide prevention in primary care?",
        "Compare the efficacy of different mood stabilizers in bipolar II maintenance therapy",
        "Analyze the evidence for mindfulness-based cognitive therapy in relapse prevention for depression",
        "What is the optimal approach to benzodiazepine tapering in long-term anxiety patients?",
        "Evaluate the role of pharmacogenomic testing in psychotropic medication selection",
    ],
    "Neurological": [
        "What are the latest advances in anti-amyloid antibody therapies for early Alzheimer's disease?",
        "Compare disease-modifying therapies for relapsing-remitting multiple sclerosis efficacy and safety",
        "Analyze the evidence for deep brain stimulation in treatment-resistant Parkinson's disease",
        "What is the current evidence on tenecteplase vs alteplase for acute ischemic stroke?",
        "Evaluate the role of CSF biomarkers and PET imaging in preclinical Alzheimer's diagnosis",
        "What are the latest clinical trial results for antisense oligonucleotides in ALS treatment?",
        "Compare preventive migraine treatments including CGRP monoclonal antibodies",
        "Analyze the evidence for vagus nerve stimulation in drug-resistant epilepsy",
        "What is the state of research on alpha-synuclein-targeting therapies for Parkinson's disease?",
        "Evaluate telemedicine-based stroke networks and their impact on thrombolysis access",
        "What are the diagnostic criteria and treatment options for autoimmune encephalitis?",
        "Compare the efficacy of different seizure prophylaxis regimens after traumatic brain injury",
        "Analyze the evidence for exercise interventions in slowing cognitive decline in mild cognitive impairment",
        "What is the optimal management of cerebral small vessel disease and its cognitive impact?",
        "Evaluate the role of wearable devices in monitoring Parkinson's disease progression",
    ],
    "Respiratory": [
        "What are the latest advances in biologic therapies for severe eosinophilic asthma?",
        "Compare antifibrotic agents pirfenidone and nintedanib for idiopathic pulmonary fibrosis",
        "Analyze the evidence for high-flow nasal cannula vs non-invasive ventilation in acute respiratory failure",
        "What is the current evidence on lung cancer screening with low-dose CT in high-risk populations?",
        "Evaluate the role of endobronchial valve therapy in severe emphysema management",
        "What are the latest clinical trial results for tezepelumab in uncontrolled asthma?",
        "Compare triple therapy inhalers for COPD exacerbation reduction",
        "Analyze the evidence for pulmonary rehabilitation telehealth programs in COPD management",
        "What is the state of research on long COVID pulmonary sequelae and treatment approaches?",
        "Evaluate biomarker-guided antibiotic stewardship in community-acquired pneumonia",
        "What are the risk prediction models for acute respiratory distress syndrome progression?",
        "Compare the efficacy of different bronchial thermoplasty techniques in refractory asthma",
        "Analyze the evidence for early palliative care integration in advanced lung cancer",
        "What is the optimal management of pulmonary arterial hypertension combination therapy?",
        "Evaluate the role of exhaled nitric oxide monitoring in personalizing asthma therapy",
    ],
}


# ---------------------------------------------------------------------------
# Profile generation (standalone — no Streamlit dependency)
# ---------------------------------------------------------------------------

_recent_queries: collections.deque = collections.deque(maxlen=45)


def _pick_query(domain: str) -> str:
    """Pick a query for the domain, avoiding recent repeats."""
    pool = DOMAIN_QUERIES.get(domain, DOMAIN_QUERIES["Cardiac"])
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
        "Physician": RequesterPersona.PHYSICIAN,
        "Hospital_Administrator": RequesterPersona.HOSPITAL_ADMINISTRATOR,
        "Pharmaceutical_Researcher": RequesterPersona.PHARMACEUTICAL_RESEARCHER,
        "Public_Health_Official": RequesterPersona.PUBLIC_HEALTH_OFFICIAL,
        "Patient_Advocate": RequesterPersona.PATIENT_ADVOCATE,
        "Medical_Student": RequesterPersona.MEDICAL_STUDENT,
    }
    type_map = {
        "Clinical_Evidence_Review": ResearchType.CLINICAL_EVIDENCE_REVIEW,
        "Drug_Interaction_Analysis": ResearchType.DRUG_INTERACTION_ANALYSIS,
        "Epidemiological_Assessment": ResearchType.EPIDEMIOLOGICAL_ASSESSMENT,
        "Treatment_Protocol_Comparison": ResearchType.TREATMENT_PROTOCOL_COMPARISON,
        "Regulatory_FDA_Analysis": ResearchType.REGULATORY_FDA_ANALYSIS,
        "Health_Policy_Evaluation": ResearchType.HEALTH_POLICY_EVALUATION,
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
# Worker: one health research session per container
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
    """Run the health research agent on a single synthetic profile."""
    import sys
    import os
    import time
    sys.path.insert(0, "/app")
    _ensure_env_vars()

    profile_id = task_spec["profile_id"]
    domain = task_spec["domain"]
    persona = task_spec["persona"]
    research_type = task_spec["research_type"]
    forced_behavior = task_spec.get("forced_behavior")  # None for normal runs

    # Set session ID for tracing
    os.environ["JUDGMENT_SESSION_ID"] = f"modal-{profile_id}-{_uuid.uuid4().hex[:8]}"

    from models import QueryProfile
    from agent import HealthResearchAgent
    from tracing import flush_and_shutdown

    # Build profile — use replay_profile if provided (exact query replay),
    # otherwise generate a new one with a random query.
    if "replay_profile" in task_spec:
        from models import ResearchType, Complexity, TimeSensitivity, RequesterPersona, DepthPreference
        rp = task_spec["replay_profile"]
        profile = QueryProfile(
            id=profile_id,
            query=rp["query"],
            research_type=ResearchType(rp["research_type"]),
            domain=rp["domain"],
            complexity=Complexity(rp["complexity"]),
            time_sensitivity=TimeSensitivity(rp["time_sensitivity"]),
            requester_persona=RequesterPersona(rp["requester_persona"]),
            depth_preference=DepthPreference(rp["depth_preference"]),
            sub_questions=rp.get("sub_questions", []),
            expected_sources=rp.get("expected_sources", 5),
            edge_case_tags=rp.get("edge_case_tags", []),
        )
    else:
        profile = generate_profile(profile_id, domain, persona, research_type)

    # Look up session depth based on profile attributes
    depth_key = (profile.complexity.value, profile.depth_preference.value)
    base_turns, max_tool_rounds = SESSION_DEPTH.get(depth_key, (6, 3))
    max_turns = max(1, base_turns + random.choice([-1, 0, 0, 1]))  # ±1 jitter, biased toward base

    # Run session
    start = time.time()
    try:
        agent = HealthResearchAgent(profile=profile, verbose=False,
                                    max_conversation_turns=max_turns,
                                    max_tool_rounds=max_tool_rounds,
                                    forced_behavior=forced_behavior)
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
    """Generate health research profiles with CycleDeck, then run the agent on each."""
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
        pid = f"health_{_uuid.uuid4().hex[:8]}"
        task_specs.append({
            "profile_id": pid,
            "domain": domains[i],
            "persona": personas[i],
            "research_type": research_types[i],
        })

    print(f"Running {count} health research sessions...")
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
    (out_dir / "health_summary.json").write_text(json.dumps(summary, indent=2))
    results_volume.commit()

    print(f"\n{'='*60}")
    print(f"HEALTH EVAL SUMMARY — {summary['run_id']}")
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
def cron_health():
    """Scheduled health research eval — trickle traffic at ~2-3 runs/hour."""
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
    # Quartered from original to keep costs down.
    if is_weekend:
        base_count = 1 if 10 <= hour < 20 else 0
    elif 9 <= hour < 18:  # business hours
        base_count = random.randint(0, 1)
    elif 18 <= hour < 22:  # evening
        base_count = random.randint(0, 1)
    else:  # late night / early morning
        base_count = 0

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
# Behavior injection: generate traces with forced clinical behaviors
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=secrets,
    volumes={"/results": results_volume},
    timeout=14400,
)
def run_behavior_batch(behavior: str, count: int = 10, seed: Optional[int] = None) -> dict:
    """Run a batch forcing a specific clinical behavior scenario."""
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
        pid = f"beh_{behavior[:4]}_{_uuid.uuid4().hex[:8]}"
        task_specs.append({
            "profile_id": pid,
            "domain": domains[i],
            "persona": personas[i],
            "research_type": research_types[i],
            "forced_behavior": behavior,
        })

    print(f"Running {count} {behavior.upper()} behavior sessions...")
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
                "forced_behavior": behavior,
            })
        else:
            results.append(r)

    results_volume.commit()

    resolved = sum(1 for r in results if r.get("resolved"))
    errors = sum(1 for r in results if r.get("error"))
    total_tokens = sum(r.get("tokens", 0) for r in results)

    now = datetime.now(timezone.utc)
    summary = {
        "run_id": f"behavior_{behavior}_{now.strftime('%Y-%m-%d_%H%M%S')}",
        "behavior": behavior,
        "total": len(results),
        "resolved": resolved,
        "errors": errors,
        "total_tokens": total_tokens,
        "results": results,
    }

    out_dir = Path(f"/results/runs/{summary['run_id']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "behavior_summary.json").write_text(json.dumps(summary, indent=2))
    results_volume.commit()

    print(f"\n{'='*60}")
    print(f"BEHAVIOR INJECTION — {behavior.upper()}")
    print(f"  Resolved: {resolved}/{len(results)}")
    print(f"  Errors:   {errors}")
    print(f"  Tokens:   {total_tokens:,}")
    print(f"{'='*60}")

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=secrets,
    volumes={"/results": results_volume},
    timeout=14400,
)
def run_replay_batch(profiles_json: str) -> dict:
    """Replay exact profiles from a JSON string (same queries, same metadata)."""
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    profiles = json.loads(profiles_json)
    count = len(profiles)

    task_specs = []
    for p in profiles:
        task_specs.append({
            "profile_id": p["id"],
            "domain": p["domain"],
            "persona": p["requester_persona"],
            "research_type": p["research_type"],
            "replay_profile": p,
        })

    print(f"Replaying {count} exact profiles...")

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
            })
        else:
            results.append(r)

    results_volume.commit()

    resolved = sum(1 for r in results if r.get("resolved"))
    errors = sum(1 for r in results if r.get("error"))
    total_tokens = sum(r.get("tokens", 0) for r in results)

    now = datetime.now(timezone.utc)
    summary = {
        "run_id": f"replay_{now.strftime('%Y-%m-%d_%H%M%S')}",
        "mode": "replay",
        "total": len(results),
        "resolved": resolved,
        "errors": errors,
        "total_tokens": total_tokens,
        "results": results,
    }

    out_dir = Path(f"/results/runs/{summary['run_id']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "replay_summary.json").write_text(json.dumps(summary, indent=2))
    results_volume.commit()

    print(f"\n{'='*60}")
    print(f"REPLAY SUMMARY — {summary['run_id']}")
    print(f"  Resolved: {resolved}/{len(results)}")
    print(f"  Errors:   {errors}")
    print(f"  Tokens:   {total_tokens:,}")
    print(f"{'='*60}")

    return summary


@app.local_entrypoint()
def main(count: int = 10, seed: Optional[int] = None, behavior: Optional[str] = None,
         replay: Optional[str] = None):
    """Run health research eval from the command line.

    --behavior emergency_escalation|medication_conflict|diagnostic_uncertainty|non_adherent|second_opinion
    --replay path/to/profiles.json  → replay exact queries from a profiles file
    --count 0  → debug tracing
    """
    if count == 0 and not behavior and not replay:
        result = debug_tracing.remote()
        print(result)
        return

    if replay:
        import os
        with open(replay) as f:
            profiles_json = f.read()
        profiles = json.loads(profiles_json)
        print(f"Replaying {len(profiles)} profiles from {replay}")
        summary = run_replay_batch.remote(profiles_json=profiles_json)
        print(f"\nReplay: {summary['resolved']}/{summary['total']} resolved")
        print(f"Total tokens: {summary['total_tokens']:,}")
        return

    if behavior:
        valid = ["emergency_escalation", "medication_conflict", "diagnostic_uncertainty",
                 "non_adherent", "second_opinion"]
        if behavior not in valid:
            print(f"Invalid behavior '{behavior}'. Choose from: {valid}")
            return
        summary = run_behavior_batch.remote(behavior=behavior, count=count, seed=seed)
        print(f"\nBehavior injection ({behavior}): {summary['resolved']}/{summary['total']} resolved")
        print(f"Total tokens: {summary['total_tokens']:,}")
        return

    summary = run_batch.remote(count=count, seed=seed)
    print(f"\nHealth eval: {summary['resolved']}/{summary['total']} resolved")
    print(f"Total tokens: {summary['total_tokens']:,}")
