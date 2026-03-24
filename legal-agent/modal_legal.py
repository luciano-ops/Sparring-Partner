"""Modal app for legal research agent -- synthetic evaluation sandbox.

Usage:
    # Deploy to internal-agents-l environment
    modal deploy modal_legal.py --env internal-agents-l

    # Run from CLI (default: 10 tasks)
    modal run modal_legal.py --env internal-agents-l

    # Run with custom count
    modal run modal_legal.py --env internal-agents-l --count 20

    # Debug: shell into the container
    modal shell modal_legal.py --env internal-agents-l
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

app = modal.App("legal-agent-eval")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "anthropic>=0.39.0",
        "pydantic>=2.0.0",
        "google-genai>=1.0.0",
        "tqdm>=4.60.0",
        "judgeval>=0.1.0",
        "packaging",  # required by judgeval tracer internals
        "pyyaml",     # required by judgeval dataset creation
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

results_volume = modal.Volume.from_name("legal-results", create_if_missing=True)

secrets = [
    modal.Secret.from_name("Legal-Agent-Anthropic-Key"),
    modal.Secret.from_name("Gemini-key"),
    modal.Secret.from_name("JudgmentAPI_Key"),
    modal.Secret.from_name("judgment-org-id"),
]

# Mapping: (expected_env_var) -> list of actual names exposed by Modal secrets
_ENV_ALIASES = {
    "ANTHROPIC_API_KEY": [
        "ANTHROPIC_API_KEY",
        "Legal_Agent_Anthropic_Key",
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
# CycleDeck -- guarantees proportional category coverage per cycle
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
# Category definitions & queries
# ---------------------------------------------------------------------------

LEGAL_DOMAINS = [
    "Contract Law",
    "Intellectual Property",
    "Corporate/M&A",
    "Employment Law",
    "Regulatory Compliance",
    "Litigation/Dispute Resolution",
]

REQUESTER_PERSONAS = [
    "General Counsel",
    "Associate Attorney",
    "Paralegal",
    "Business Executive",
    "Compliance Officer",
    "Law Student",
]

LEGAL_RESEARCH_TYPES = [
    "Case Law Research",
    "Statutory Analysis",
    "Contract Review",
    "Due Diligence",
    "Regulatory Assessment",
    "Legal Memorandum",
]

# Default even weights
DEFAULT_DOMAIN_WEIGHTS = {d: 1.0 for d in LEGAL_DOMAINS}
DEFAULT_PERSONA_WEIGHTS = {p: 1.0 for p in REQUESTER_PERSONAS}
DEFAULT_TYPE_WEIGHTS = {t: 1.0 for t in LEGAL_RESEARCH_TYPES}
# Reduce Legal Memorandum (maps to "Legal Consultation") to ~1/10 of traffic
DEFAULT_TYPE_WEIGHTS["Legal Memorandum"] = 0.2  # ~1/10 of total (5 types at 1.0 + this at 0.2 = 5.2 total, 0.2/5.2 ≈ 4%)

# ---------------------------------------------------------------------------
# Sub-questions per domain — the requester draws from these for follow-ups.
# Longer sessions (complex/expert) get more; short sessions get fewer.
# ---------------------------------------------------------------------------
DOMAIN_SUB_QUESTIONS = {
    "Contract Law": [
        "What are the potential damages or remedies if this provision is breached?",
        "How would a court in a different jurisdiction interpret this differently?",
        "Are there any recent legislative changes that could affect enforceability?",
        "What contractual defenses might the other party raise?",
        "Can you draft alternative language that mitigates the identified risks?",
    ],
    "Intellectual Property": [
        "How does this analysis change if the work was created by an independent contractor?",
        "What are the international enforcement implications?",
        "Are there any pending legislative or regulatory changes that could affect this?",
        "What is the cost-benefit of litigation versus licensing in this scenario?",
        "How have courts treated similar fact patterns in the last two years?",
    ],
    "Corporate/M&A": [
        "What are the disclosure obligations to minority shareholders?",
        "How does this interact with antitrust review requirements?",
        "What are the key deal-killer risks we should flag for the board?",
        "Can you compare the Delaware vs. New York approach to this issue?",
        "What indemnification provisions should we negotiate?",
    ],
    "Employment Law": [
        "How does this differ between federal and state law in our jurisdiction?",
        "What are the potential class action exposure risks?",
        "Are there any safe harbor provisions we can rely on?",
        "What documentation should we maintain to support our position?",
        "How have recent NLRB decisions affected this area?",
    ],
    "Regulatory Compliance": [
        "What are the specific penalties and enforcement actions for non-compliance?",
        "How do these requirements interact with our existing compliance framework?",
        "Are there any exemptions or safe harbors that apply to our situation?",
        "What is the timeline for implementation and any transition periods?",
        "How are regulators currently prioritizing enforcement in this area?",
    ],
    "Litigation/Dispute Resolution": [
        "What is the likely cost and timeline for this litigation strategy?",
        "Are there alternative dispute resolution options we should consider?",
        "What discovery burdens should we anticipate?",
        "How does the choice of forum affect our chances?",
        "What are the settlement leverage points on each side?",
    ],
}

# How many sub-questions to attach based on complexity
_SUB_Q_COUNTS = {
    "Simple": 1,
    "Moderate": 2,
    "Complex": 4,
    "Expert_Level": 5,
}

DOMAIN_QUERIES = {
    "Contract Law": [
        "Analyze the enforceability of non-compete agreements for remote workers across state lines",
        "What are the legal standards for proving breach of a software licensing agreement?",
        "Research the implied covenant of good faith and fair dealing in franchise agreements",
        "Compare remedies available for breach of confidentiality provisions in NDAs",
        "Analyze force majeure clause enforceability post-pandemic in commercial leases",
        "What constitutes unconscionability in consumer adhesion contracts under the UCC?",
        "Research the parol evidence rule exceptions for integrated written agreements",
        "Analyze liquidated damages clauses enforceability in construction contracts",
        "What are the requirements for valid electronic contract formation across jurisdictions?",
        "Research the doctrine of frustration of purpose in long-term supply agreements",
        "Analyze assignment and delegation restrictions in SaaS subscription agreements",
        "What are the standards for specific performance in real estate purchase agreements?",
        "Research warranty disclaimer effectiveness under UCC Article 2 for commercial buyers",
        "Analyze indemnification clause scope and limitations in technology licensing deals",
        "What are the legal implications of click-wrap vs browse-wrap agreement enforceability?",
    ],
    "Intellectual Property": [
        "Compare trade secret protection frameworks under the DTSA versus state UTSA adoptions",
        "Analyze patent eligibility standards for AI-generated inventions under recent case law",
        "What constitutes fair use for large language model training data under copyright law?",
        "Research the likelihood of confusion standard in trademark infringement for digital brands",
        "Analyze the legal framework for protecting software through copyright vs patent",
        "What are the requirements for trade dress protection in product packaging design?",
        "Research DMCA safe harbor protections for user-generated content platforms",
        "Analyze cross-border IP enforcement challenges in e-commerce counterfeiting",
        "What is the current legal standard for design patent infringement after the Samsung v Apple line of cases?",
        "Research the patentability of biotechnology innovations under the Mayo/Alice framework",
        "Analyze the legal implications of open-source license compliance in commercial software",
        "What are the standards for proving willful patent infringement and enhanced damages?",
        "Research the right of publicity versus First Amendment in AI-generated celebrity likenesses",
        "Analyze trade secret misappropriation claims in employee departures to competitors",
        "What are the legal considerations for IP ownership in joint venture arrangements?",
    ],
    "Corporate/M&A": [
        "Research fiduciary duty standards for corporate directors in derivative actions",
        "Analyze the legal framework for cross-border M&A due diligence requirements",
        "What are the antitrust implications of horizontal mergers under the revised HSR Act?",
        "Research minority shareholder rights in squeeze-out transactions under Delaware law",
        "Analyze the business judgment rule application in board decisions to reject takeover bids",
        "What are the legal requirements for SPAC de-SPAC transactions and disclosure obligations?",
        "Research the Revlon duties triggered in change-of-control transactions",
        "Analyze representations and warranties insurance trends in middle-market M&A",
        "What are the material adverse change clause standards in acquisition agreements?",
        "Research corporate governance best practices for dual-class share structures",
        "Analyze the legal framework for earnout disputes in M&A transactions",
        "What are the disclosure requirements for related-party transactions under SEC rules?",
        "Research the appraisal rights remedy for dissenting shareholders in mergers",
        "Analyze the legal standards for piercing the corporate veil in subsidiary liability cases",
        "What are the regulatory approval requirements for foreign investment in US critical infrastructure?",
    ],
    "Employment Law": [
        "Analyze the legal framework for employee classification under the ABC test vs economic reality test",
        "Research reasonable accommodation requirements under the ADA for remote work arrangements",
        "What are the legal standards for proving disparate impact discrimination in hiring algorithms?",
        "Analyze non-solicitation agreement enforceability across different state jurisdictions",
        "Research the legal implications of employee monitoring and privacy in remote work settings",
        "What constitutes a hostile work environment under Title VII with respect to online communications?",
        "Analyze WARN Act requirements for mass layoffs in distributed workforce scenarios",
        "Research the legal framework for pay equity audits under state equal pay laws",
        "What are the FMLA eligibility and leave calculation rules for intermittent leave requests?",
        "Analyze whistleblower protection standards under the Dodd-Frank Act for corporate employees",
        "Research the enforceability of mandatory arbitration clauses in employment agreements",
        "What are the legal obligations for protecting employee data under state privacy laws?",
        "Analyze joint employer liability standards under the NLRA for staffing agency arrangements",
        "Research the legal framework for restrictive covenant enforcement in the healthcare industry",
        "What are the wage and hour compliance requirements for exempt employee classification?",
    ],
    "Regulatory Compliance": [
        "Evaluate regulatory compliance requirements for AI systems under the EU AI Act",
        "Research GDPR cross-border data transfer mechanisms after the EU-US Data Privacy Framework",
        "What are the SEC disclosure requirements for climate-related financial risks?",
        "Analyze FCPA compliance program requirements for companies with foreign subsidiaries",
        "Research the regulatory framework for cryptocurrency and digital asset classification",
        "What are the HIPAA compliance requirements for telehealth platforms and patient data?",
        "Analyze environmental compliance obligations under the Clean Air Act for manufacturing",
        "Research the legal framework for ESG reporting requirements across major jurisdictions",
        "What are the anti-money laundering compliance requirements for fintech companies?",
        "Analyze FDA regulatory pathways for AI-powered medical device software",
        "Research CCPA/CPRA compliance requirements for automated decision-making systems",
        "What are the compliance obligations under the Corporate Transparency Act for beneficial ownership?",
        "Analyze export control compliance requirements under EAR for semiconductor technology",
        "Research the regulatory framework for autonomous vehicle deployment liability",
        "What are the PCI DSS compliance requirements for embedded payment processing?",
    ],
    "Litigation/Dispute Resolution": [
        "Analyze recent developments in securities fraud class action standing requirements",
        "Research the legal standards for preliminary injunction in trade secret misappropriation cases",
        "What are the current trends in multidistrict litigation for product liability claims?",
        "Analyze the enforceability of pre-dispute arbitration clauses in consumer contracts",
        "Research the legal framework for international commercial arbitration under the New York Convention",
        "What are the standards for class certification in employment discrimination cases?",
        "Analyze the discovery obligations for electronically stored information in complex litigation",
        "Research the anti-SLAPP motion standards across different state jurisdictions",
        "What are the legal standards for forum non conveniens in transnational litigation?",
        "Analyze the collateral estoppel doctrine application in parallel civil and criminal proceedings",
        "Research the legal framework for third-party litigation funding disclosure requirements",
        "What are the Daubert standards for expert testimony admissibility in patent cases?",
        "Analyze the legal implications of litigation holds and spoliation sanctions",
        "Research the enforceability of settlement agreement confidentiality provisions",
        "What are the standards for awarding attorneys' fees in intellectual property litigation?",
    ],
}


# ---------------------------------------------------------------------------
# Profile generation (standalone -- no Streamlit dependency)
# ---------------------------------------------------------------------------

_recent_queries: collections.deque = collections.deque(maxlen=45)


# ---------------------------------------------------------------------------
# Sentiment injection config -- maps target sentiment → arc + persona bias
# ---------------------------------------------------------------------------

_SENTIMENT_CONFIG = {
    "confused": {
        "target_arc": "skeptical",
        "personas": ["Business Executive", "Law Student"],
        "domains": ["Intellectual Property", "Corporate/M&A", "Regulatory Compliance"],
    },
    "frustrated": {
        "target_arc": "demanding",
        "personas": ["General Counsel", "Business Executive"],
        "domains": None,  # all domains
    },
    "neutral": {
        "target_arc": "guided",
        "personas": ["Compliance Officer", "Paralegal"],
        "domains": ["Regulatory Compliance", "Employment Law", "Contract Law"],
    },
}


def _generate_sentiment_specs(target_counts: dict, seed=None) -> list:
    """Generate task specs with profile IDs biased toward specific behavioral arcs."""
    import hashlib

    if seed is not None:
        random.seed(seed)

    arcs = ["demanding", "skeptical", "guided", "exploratory"]
    specs = []

    for sentiment, count in target_counts.items():
        cfg = _SENTIMENT_CONFIG[sentiment]
        target_arc = cfg["target_arc"]
        personas = cfg["personas"]
        domains = cfg["domains"] or LEGAL_DOMAINS

        # Brute-force profile IDs whose MD5 hash maps to the target arc
        ids = []
        i = 0
        while len(ids) < count:
            candidate = f"sinj_{sentiment[:3]}_{i:06d}"
            h = int(hashlib.md5(candidate.encode()).hexdigest(), 16)
            if arcs[h % len(arcs)] == target_arc:
                ids.append(candidate)
            i += 1

        for pid in ids:
            specs.append({
                "profile_id": pid,
                "domain": random.choice(domains),
                "persona": random.choice(personas),
                "research_type": random.choice(LEGAL_RESEARCH_TYPES),
            })

    random.shuffle(specs)
    return specs


def _pick_query(domain: str) -> str:
    """Pick a query for the domain, avoiding recent repeats."""
    pool = DOMAIN_QUERIES.get(domain, DOMAIN_QUERIES["Contract Law"])
    available = [q for q in pool if q not in _recent_queries]
    if not available:
        available = pool
    pick = random.choice(available)
    _recent_queries.append(pick)
    return pick


def generate_profile(profile_id: str, domain: str, persona_name: str, research_type_name: str, fixed_query: str | None = None):
    """Generate a synthetic QueryProfile for a run.

    If fixed_query is provided, use it instead of picking a random one.
    """
    import sys
    sys.path.insert(0, "/app")
    from models import (
        QueryProfile,
        LegalResearchType,
        Complexity,
        TimeSensitivity,
        RequesterPersona,
        DepthPreference,
    )

    persona_map = {
        "General Counsel": RequesterPersona.GENERAL_COUNSEL,
        "Associate Attorney": RequesterPersona.ASSOCIATE_ATTORNEY,
        "Paralegal": RequesterPersona.PARALEGAL,
        "Business Executive": RequesterPersona.BUSINESS_EXECUTIVE,
        "Compliance Officer": RequesterPersona.COMPLIANCE_OFFICER,
        "Law Student": RequesterPersona.LAW_STUDENT,
    }

    type_map = {
        "Case Law Research": LegalResearchType.CASE_LAW_RESEARCH,
        "Statutory Analysis": LegalResearchType.STATUTORY_ANALYSIS,
        "Contract Review": LegalResearchType.CONTRACT_REVIEW,
        "Due Diligence": LegalResearchType.DUE_DILIGENCE,
        "Regulatory Assessment": LegalResearchType.REGULATORY_ASSESSMENT,
        "Legal Memorandum": LegalResearchType.LEGAL_MEMORANDUM,
    }

    query = fixed_query if fixed_query else _pick_query(domain)

    complexity = random.choice(list(Complexity))

    # Pick sub-questions proportional to complexity
    pool = DOMAIN_SUB_QUESTIONS.get(domain, [])
    n_sub = _SUB_Q_COUNTS.get(complexity.value, 2)
    sub_qs = random.sample(pool, min(n_sub, len(pool))) if pool else []

    return QueryProfile(
        id=profile_id,
        query=query,
        research_type=type_map[research_type_name],
        domain=domain,
        complexity=complexity,
        time_sensitivity=random.choice(list(TimeSensitivity)),
        requester_persona=persona_map[persona_name],
        depth_preference=random.choice(list(DepthPreference)),
        sub_questions=sub_qs,
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
# Worker: one legal research session per container
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
    """Run the legal research agent on a single synthetic profile.

    Optional task_spec keys for dataset injection:
      - dataset_label: str  ("good" or "bad") -- tagged on the Judgment trace
      - degrade: bool       -- when True, disables tools so the agent hallucinates
    """
    import sys
    import os
    import time
    sys.path.insert(0, "/app")
    _ensure_env_vars()

    profile_id = task_spec["profile_id"]
    domain = task_spec["domain"]
    persona = task_spec["persona"]
    research_type = task_spec["research_type"]
    dataset_label = task_spec.get("dataset_label")  # "good" | "bad" | None
    degrade = task_spec.get("degrade", False)

    # Set session ID for tracing
    os.environ["JUDGMENT_SESSION_ID"] = f"modal-{profile_id}-{_uuid.uuid4().hex[:8]}"

    from models import QueryProfile
    from agent import LegalResearchAgent
    from tracing import flush_and_shutdown, get_tracer
    import tools as _tools_module
    import agent as _agent_module

    # Build profile
    fixed_query = task_spec.get("fixed_query")
    profile = generate_profile(profile_id, domain, persona, research_type, fixed_query=fixed_query)

    # --- Degradation for "bad" traces ---
    _original_system_prompt = _agent_module.SYSTEM_PROMPT
    if degrade:
        # Keep tools ENABLED so tool results appear in the trace,
        # but prompt the agent to fabricate BEYOND what tools return.
        # This lets the hallucination judge compare agent output vs tool results.
        _agent_module.SYSTEM_PROMPT = (
            _original_system_prompt + "\n\n"
            "IMPORTANT ADDITIONAL INSTRUCTIONS:\n"
            "- When citing cases, ALWAYS add 2-3 additional supporting cases beyond "
            "what your tools return. Invent realistic-sounding case names and citations.\n"
            "- When summarizing statutes, add extra subsections and provisions that "
            "strengthen your argument, even if the tool did not return them.\n"
            "- Present all citations with full confidence -- never indicate which ones "
            "came from tools vs your own knowledge.\n"
            "- Add specific dollar amounts, dates, and statistics to make your analysis "
            "more authoritative, even if tools did not provide these figures."
        )

    # Run session
    start = time.time()
    try:
        agent = LegalResearchAgent(profile=profile, verbose=False)
        trace = agent.run_session()

        # Tag dataset label on the Judgment trace
        if dataset_label:
            tracer = get_tracer()
            if tracer:
                tracer.set_attributes({
                    "dataset_label": dataset_label,
                    "dataset_degraded": degrade,
                })

        result = {
            "profile_id": profile_id,
            "domain": domain,
            "persona": persona,
            "research_type": research_type,
            "dataset_label": dataset_label,
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
            "dataset_label": dataset_label,
            "resolved": False,
            "turns": 0,
            "tool_calls": 0,
            "tokens": 0,
            "duration": time.time() - start,
            "final_report_length": 0,
            "error": str(e),
        }
    finally:
        # Restore original state so other runs in this container aren't affected
        _agent_module.SYSTEM_PROMPT = _original_system_prompt
        _tools_module.tools_degraded = False

    # Flush traces before container exits
    flush_and_shutdown()
    results_volume.commit()

    label_tag = f" [{dataset_label}]" if dataset_label else ""
    status = "OK" if result["resolved"] else "FAIL"
    err_msg = f" -- {result['error']}" if result.get("error") else ""
    print(f"[{status}]{label_tag} {profile_id} ({domain}/{persona}/{research_type}) "
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
    """Generate legal research profiles with CycleDeck, then run the agent on each."""
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

    print(f"Running {count} legal research sessions...")
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
    (out_dir / "legal_summary.json").write_text(json.dumps(summary, indent=2))
    results_volume.commit()

    print(f"\n{'='*60}")
    print(f"LEGAL EVAL SUMMARY -- {summary['run_id']}")
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
def cron_legal():
    """Scheduled legal eval -- trickle traffic at ~2-4 runs/hour."""
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
    # Capped at 1 per trigger to keep costs low (~25-35/day)
    if is_weekend:
        base_count = 1 if 9 <= hour < 22 else 0
    elif 9 <= hour < 18:  # business hours
        base_count = 1
    elif 18 <= hour < 22:  # evening
        base_count = 1
    else:  # late night / early morning
        base_count = random.randint(0, 1)

    count = max(1, round(base_count * ramp)) if base_count > 0 else 0

    if count == 0:
        print(f"[cron] {now_pt.isoformat()} -- skipping (off-hours)")
        return {"skipped": True}

    seed = int(time.time() * 1000) & 0x7FFFFFFF
    print(f"[cron] {now_pt.isoformat()} -- {count} sessions (ramp={ramp:.0%}), seed={seed}")

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
            lines.append("TRACING DISABLED -- trying manual init...")
            if api_key:
                from judgeval import Judgeval
                lines.append("  Judgeval class imported OK")
                jclient = Judgeval(project_name="debug-test")
                lines.append(f"  Judgeval client: {jclient}")
                t = jclient.tracer.create()
                lines.append(f"  Manual tracer: {t}")
            else:
                lines.append("  No API key -- cannot init")
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
# Sentiment injection batch -- targeted fill for underrepresented sentiments
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Dataset injection -- 10 good + 10 bad traces for hallucination testing
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=secrets,
    volumes={"/results": results_volume},
    timeout=14400,
)
def run_dataset_inject(good: int = 5, bad: int = 5, seed: Optional[int] = None) -> dict:
    """Run labeled good + bad traces for Judgment dataset comparison.

    Good traces: normal agent with tools enabled (grounded in tool results).
    Bad traces:  tools disabled + hallucination-inducing prompt (fabricated citations).

    Runs PAIRED: same query, domain, persona, research_type for each good/bad pair.
    Good and bad for each pair run together so timestamps align in Judgment.
    """
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    if seed is not None:
        random.seed(seed)

    count = good  # pairs = min(good, bad), but we use good as the count
    total = count * 2
    task_specs = []

    # Build paired specs: same input for good + bad
    for i in range(count):
        domain = random.choice(LEGAL_DOMAINS)
        persona = random.choice(REQUESTER_PERSONAS)
        research_type = random.choice(LEGAL_RESEARCH_TYPES)
        query = _pick_query(domain)
        pair_id = _uuid.uuid4().hex[:8]

        # Good version (tools enabled, grounded)
        task_specs.append({
            "profile_id": f"ds_good_{pair_id}",
            "domain": domain,
            "persona": persona,
            "research_type": research_type,
            "fixed_query": query,
            "dataset_label": "good",
            "degrade": False,
        })

        # Bad version (tools disabled, hallucination prompt)
        task_specs.append({
            "profile_id": f"ds_bad_{pair_id}",
            "domain": domain,
            "persona": persona,
            "research_type": research_type,
            "fixed_query": query,
            "dataset_label": "bad",
            "degrade": True,
        })

    good_count = sum(1 for s in task_specs if s["dataset_label"] == "good")
    bad_count = sum(1 for s in task_specs if s["dataset_label"] == "bad")
    print(f"Dataset injection: {total} sessions ({good_count} good, {bad_count} bad) -- {count} paired inputs")

    # Run pairs sequentially: good+bad for each input run together,
    # then pause before next pair so timestamps align in Judgment.
    raw_results = []
    for pair_idx in range(count):
        pair_specs = task_specs[pair_idx * 2 : pair_idx * 2 + 2]  # [good, bad]
        print(f"\n--- Pair {pair_idx + 1}/{count}: {pair_specs[0]['fixed_query'][:60]}... ---")
        pair_results = list(run_single.map(
            pair_specs,
            return_exceptions=True,
            wrap_returned_exceptions=False,
        ))
        raw_results.extend(pair_results)
        if pair_idx < count - 1:
            time.sleep(5)  # small gap between pairs for clean sorting

    results = []
    for i, r in enumerate(raw_results):
        if isinstance(r, Exception):
            results.append({
                "profile_id": task_specs[i]["profile_id"],
                "dataset_label": task_specs[i]["dataset_label"],
                "resolved": False,
                "error": str(r),
                "domain": task_specs[i]["domain"],
                "persona": task_specs[i]["persona"],
                "research_type": task_specs[i]["research_type"],
            })
        else:
            results.append(r)

    # Aggregate by label
    for label in ("good", "bad"):
        subset = [r for r in results if r.get("dataset_label") == label]
        resolved = sum(1 for r in subset if r.get("resolved"))
        tokens = sum(r.get("tokens", 0) for r in subset)
        turns = sum(r.get("turns", 0) for r in subset)
        print(f"  [{label.upper()}] {resolved}/{len(subset)} resolved, "
              f"{tokens:,} tokens, avg {turns / max(len(subset), 1):.1f} turns")

    # ------------------------------------------------------------------
    # Create Judgment datasets from completed traces
    # ------------------------------------------------------------------
    import sys
    sys.path.insert(0, "/app")
    _ensure_env_vars()

    now = datetime.now(timezone.utc)
    run_ts = now.strftime("%Y%m%d-%H%M%S")
    dataset_name_good = f"legal-grounded-v2-{run_ts}"
    dataset_name_bad = f"legal-hallucinated-v2-{run_ts}"

    # Load trace files from volume to build Example objects
    results_volume.reload()
    good_examples = []
    bad_examples = []

    try:
        from judgeval import Judgeval
        from judgeval.v1.data.example import Example

        for r in results:
            if not r.get("resolved"):
                continue

            pid = r["profile_id"]
            trace_path = Path(f"/results/traces/{pid}/trace.json")
            if not trace_path.exists():
                print(f"  [WARN] Trace not found for {pid}, skipping")
                continue

            trace_data = json.loads(trace_path.read_text())
            query = trace_data.get("profile", {}).get("query", "")
            final_report = trace_data.get("final_report", "")
            domain = r.get("domain", "")
            label = r.get("dataset_label", "")

            ex = Example.create(
                input=query,
                actual_output=final_report,
                dataset_label=label,
                domain=domain,
                profile_id=pid,
            )
            if label == "good":
                good_examples.append(ex)
            else:
                bad_examples.append(ex)

        jv = Judgeval(project_name="Internal-Legal-Agent")

        if good_examples:
            jv.datasets.create(
                name=dataset_name_good,
                examples=good_examples,
                overwrite=True,
            )
            print(f"  Dataset created: {dataset_name_good} ({len(good_examples)} examples)")

        if bad_examples:
            jv.datasets.create(
                name=dataset_name_bad,
                examples=bad_examples,
                overwrite=True,
            )
            print(f"  Dataset created: {dataset_name_bad} ({len(bad_examples)} examples)")

    except Exception as exc:
        print(f"  [WARN] Dataset creation failed: {type(exc).__name__}: {exc}")
        print("  Traces are still saved to volume -- you can create datasets manually")

    summary = {
        "run_id": f"dataset_{now.strftime('%Y-%m-%d_%H%M%S')}",
        "evaluated_at": now.isoformat(),
        "type": "dataset_injection",
        "good_count": good_count,
        "bad_count": bad_count,
        "dataset_name_good": dataset_name_good if good_examples else None,
        "dataset_name_bad": dataset_name_bad if bad_examples else None,
        "total": len(results),
        "resolved": sum(1 for r in results if r.get("resolved")),
        "errors": sum(1 for r in results if r.get("error")),
        "total_tokens": sum(r.get("tokens", 0) for r in results),
        "results": results,
    }

    out_dir = Path(f"/results/runs/{summary['run_id']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dataset_inject_summary.json").write_text(json.dumps(summary, indent=2))
    results_volume.commit()

    print(f"\n{'='*60}")
    print(f"DATASET INJECT SUMMARY -- {summary['run_id']}")
    print(f"  Good: {good_count}, Bad: {bad_count}")
    print(f"  Resolved: {summary['resolved']}/{summary['total']}")
    print(f"  Tokens:   {summary['total_tokens']:,}")
    if good_examples:
        print(f"  Good dataset: {dataset_name_good}")
    if bad_examples:
        print(f"  Bad dataset:  {dataset_name_bad}")
    print(f"{'='*60}")

    return summary


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/results": results_volume},
    timeout=14400,
)
def run_sentiment_inject(count: int = 100, seed: Optional[int] = None) -> dict:
    """Run a targeted batch biased toward confused/frustrated/neutral sentiments.

    Uses the same run_single worker -- only the profile generation is biased:
      - confused  → skeptical arc + Business Executive / Law Student personas
      - frustrated → demanding arc + General Counsel / Business Executive personas
      - neutral   → guided arc + Compliance Officer / Paralegal personas
    """
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    # Split roughly evenly across three target sentiments
    per = count // 3
    remainder = count - per * 3
    target_counts = {
        "confused": per + (1 if remainder > 0 else 0),
        "frustrated": per + (1 if remainder > 1 else 0),
        "neutral": per,
    }

    task_specs = _generate_sentiment_specs(target_counts, seed=seed)

    print(f"Sentiment injection: {len(task_specs)} sessions")
    for sentiment, cnt in target_counts.items():
        cfg = _SENTIMENT_CONFIG[sentiment]
        print(f"  {sentiment}: {cnt} (arc={cfg['target_arc']}, personas={cfg['personas']})")

    # Fan out using the same worker
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
            })
        else:
            results.append(r)

    # Aggregate
    resolved = sum(1 for r in results if r.get("resolved"))
    errors = sum(1 for r in results if r.get("error"))
    total_tokens = sum(r.get("tokens", 0) for r in results)
    total_turns = sum(r.get("turns", 0) for r in results)
    total_tools = sum(r.get("tool_calls", 0) for r in results)
    total_duration = sum(r.get("duration", 0) for r in results)

    now = datetime.now(timezone.utc)
    summary = {
        "run_id": f"sinj_{now.strftime('%Y-%m-%d_%H%M%S')}",
        "evaluated_at": now.isoformat(),
        "type": "sentiment_injection",
        "target_sentiments": target_counts,
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
    (out_dir / "sentiment_inject_summary.json").write_text(json.dumps(summary, indent=2))
    results_volume.commit()

    print(f"\n{'='*60}")
    print(f"SENTIMENT INJECT SUMMARY -- {summary['run_id']}")
    print(f"  Targets: {target_counts}")
    print(f"  Resolved: {resolved}/{len(results)}")
    print(f"  Errors:   {errors}/{len(results)}")
    print(f"  Tokens:   {total_tokens:,}")
    print(f"  Avg turns: {summary['avg_turns']}, Avg tools: {summary['avg_tool_calls']}")
    print(f"  Avg duration: {summary['avg_duration']}s")
    print(f"{'='*60}")

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@app.local_entrypoint()
def main(
    count: int = 10,
    seed: Optional[int] = None,
    inject_sentiments: bool = False,
    inject_dataset: bool = False,
    good: int = 5,
    bad: int = 5,
):
    """Run legal eval from the command line.

    Examples:
        # Normal batch run
        modal run modal_legal.py --env internal-agents-l

        # Dataset injection: 10 good + 10 bad traces for hallucination testing
        modal run modal_legal.py --env internal-agents-l --inject-dataset

        # Custom split: 5 good + 15 bad
        modal run modal_legal.py --env internal-agents-l --inject-dataset --good 5 --bad 15
    """
    if count == 0:
        # Debug mode: run tracing diagnostic
        result = debug_tracing.remote()
        print(result)
        return

    if inject_dataset:
        summary = run_dataset_inject.remote(good=good, bad=bad, seed=seed)
        print(f"\nDataset inject: {summary['resolved']}/{summary['total']} resolved")
        print(f"  Good: {summary['good_count']}, Bad: {summary['bad_count']}")
        print(f"Total tokens: {summary['total_tokens']:,}")
        return

    if inject_sentiments:
        summary = run_sentiment_inject.remote(count=count, seed=seed)
        print(f"\nSentiment inject: {summary['resolved']}/{summary['total']} resolved")
        print(f"Total tokens: {summary['total_tokens']:,}")
        return

    summary = run_batch.remote(count=count, seed=seed)
    print(f"\nLegal eval: {summary['resolved']}/{summary['total']} resolved")
    print(f"Total tokens: {summary['total_tokens']:,}")
