"""
Deep Research Agent — Control Panel
Dark-themed Streamlit dashboard for configuring and running research agent traces.
"""

import collections
import json
import os
import random
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st

# ---------------------------------------------------------------------------
# Ensure project modules are importable
# ---------------------------------------------------------------------------
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from models import (
    QueryProfile,
    ResearchType,
    Complexity,
    TimeSensitivity,
    RequesterPersona,
    DepthPreference,
)
from agent import ResearchAgent
from tools import token_tracker
from tracing import get_tracer, flush

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Deep Research Agent",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Dark theme CSS matching the reference screenshot
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Main background */
    .stApp {
        background-color: #1a1a2e;
        color: #e0e0e0;
    }

    /* Header */
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #ffffff;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 0.95rem;
        color: #888;
        margin-top: -8px;
        margin-bottom: 24px;
    }

    /* Cards */
    .config-card {
        background-color: #16213e;
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 16px;
    }
    .config-card-title {
        font-size: 0.85rem;
        font-weight: 700;
        color: #f0a040;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        margin-bottom: 16px;
    }

    /* Slider rows */
    .slider-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 8px;
        padding: 4px 0;
    }
    .slider-label {
        font-size: 0.9rem;
        color: #d0d0d0;
        min-width: 180px;
    }
    .slider-bar-bg {
        flex: 1;
        height: 6px;
        background-color: #2a2a4a;
        border-radius: 3px;
        margin: 0 16px;
        position: relative;
    }
    .slider-bar-fill {
        height: 100%;
        background: linear-gradient(90deg, #e67e22, #f39c12);
        border-radius: 3px;
        transition: width 0.3s ease;
    }
    .slider-dot {
        width: 14px;
        height: 14px;
        background-color: #e67e22;
        border-radius: 50%;
        position: absolute;
        top: -4px;
        transition: left 0.3s ease;
    }
    .slider-pct {
        font-size: 0.9rem;
        font-weight: 600;
        color: #f0a040;
        min-width: 45px;
        text-align: right;
    }
    .slider-count {
        font-size: 0.8rem;
        color: #666;
        min-width: 30px;
        text-align: right;
    }

    /* Reset button */
    .reset-btn {
        float: right;
        background-color: transparent;
        border: 1px solid #e67e22;
        color: #e67e22;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 0.75rem;
        cursor: pointer;
        font-weight: 600;
    }

    /* Run button */
    .run-btn-container {
        margin: 24px 0;
    }
    div.stButton > button {
        background: linear-gradient(135deg, #e67e22, #f39c12) !important;
        color: #1a1a2e !important;
        font-size: 1.1rem !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 16px !important;
        width: 100% !important;
        cursor: pointer !important;
        letter-spacing: 0.5px !important;
    }
    div.stButton > button:hover {
        background: linear-gradient(135deg, #f39c12, #e67e22) !important;
        box-shadow: 0 4px 20px rgba(230, 126, 34, 0.4) !important;
    }

    /* Progress card */
    .progress-card {
        background-color: #16213e;
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 20px 24px;
        margin-top: 16px;
    }
    .progress-title {
        font-size: 0.85rem;
        font-weight: 700;
        color: #f0a040;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        margin-bottom: 12px;
    }
    .progress-bar-bg {
        width: 100%;
        height: 32px;
        background-color: #2a2a4a;
        border-radius: 8px;
        overflow: hidden;
        margin-bottom: 16px;
    }
    .progress-bar-fill {
        height: 100%;
        background: linear-gradient(90deg, #e67e22, #f39c12);
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        color: #1a1a2e;
        font-size: 0.85rem;
        transition: width 0.5s ease;
    }
    .progress-complete {
        text-align: right;
        color: #888;
        font-size: 0.85rem;
        margin-top: -8px;
        margin-bottom: 12px;
    }

    /* Stats row */
    .stats-row {
        display: flex;
        gap: 24px;
        margin-bottom: 16px;
        color: #d0d0d0;
        font-size: 0.85rem;
    }
    .stats-row strong {
        color: #ffffff;
    }

    /* Actual results */
    .actual-results {
        display: flex;
        gap: 40px;
        margin-top: 8px;
    }
    .actual-col {
        flex: 1;
    }
    .actual-col-title {
        font-size: 0.75rem;
        font-weight: 700;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }
    .actual-col-item {
        font-size: 0.8rem;
        color: #d0d0d0;
        margin-bottom: 2px;
    }

    /* Input boxes */
    .num-input {
        background-color: #2a2a4a;
        border: 1px solid #3a3a5a;
        border-radius: 8px;
        padding: 8px 16px;
        color: #ffffff;
        font-size: 1.2rem;
        font-weight: 700;
        text-align: center;
        width: 80px;
    }
    .input-label {
        font-size: 0.75rem;
        color: #888;
        margin-bottom: 4px;
    }

    /* Hide Streamlit defaults */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}

    /* Slider theming */
    .stSlider > div > div > div > div {
        background-color: #e67e22 !important;
    }
    .stSlider [data-baseweb="slider"] {
        margin-top: 0 !important;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------
RESEARCH_DOMAINS = [
    "AI/ML",
    "Finance",
    "Healthcare",
    "Climate",
    "Geopolitics",
    "Cybersecurity",
]

REQUESTER_SENTIMENTS = [
    "Executive",
    "Academic",
    "Journalist",
    "Student",
    "Analyst",
    "Curious Generalist",
]

RESEARCH_TYPES = [
    "Literature Review",
    "Market Analysis",
    "Technical Deep Dive",
    "Fact Checking",
    "Comparative Analysis",
    "Trend Research",
]

# Map display names back to enum values
_PERSONA_MAP = {
    "Executive": RequesterPersona.EXECUTIVE,
    "Academic": RequesterPersona.ACADEMIC,
    "Journalist": RequesterPersona.JOURNALIST,
    "Student": RequesterPersona.STUDENT,
    "Analyst": RequesterPersona.ANALYST,
    "Curious Generalist": RequesterPersona.CURIOUS_GENERALIST,
}

_RESEARCH_TYPE_MAP = {
    "Literature Review": ResearchType.LITERATURE_REVIEW,
    "Market Analysis": ResearchType.MARKET_ANALYSIS,
    "Technical Deep Dive": ResearchType.TECHNICAL_DEEP_DIVE,
    "Fact Checking": ResearchType.FACT_CHECKING,
    "Comparative Analysis": ResearchType.COMPARATIVE_ANALYSIS,
    "Trend Research": ResearchType.TREND_RESEARCH,
}

_COMPLEXITY_OPTIONS = list(Complexity)
_DEPTH_OPTIONS = list(DepthPreference)
_TIME_OPTIONS = list(TimeSensitivity)

# Sample queries per domain (15 each for 240 runs/day without heavy repetition)
_DOMAIN_QUERIES = {
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
# Helper: render a distribution card with sliders
# ---------------------------------------------------------------------------
def render_distribution_card(title: str, items: list[str], key_prefix: str):
    """Render a config card with percentage sliders for each item."""
    st.markdown(f"""
    <div class="config-card">
        <div class="config-card-title">{title}</div>
    </div>
    """, unsafe_allow_html=True)

    # Initialize even distribution in session state
    state_key = f"{key_prefix}_dist"
    if state_key not in st.session_state:
        even = round(100 / len(items))
        st.session_state[state_key] = {item: even for item in items}
        # Fix rounding
        diff = 100 - sum(st.session_state[state_key].values())
        st.session_state[state_key][items[0]] += diff

    updated = {}

    for item in items:
        c1, c2, c3, c4 = st.columns([3, 8, 2, 1])
        with c1:
            st.markdown(f"<span style='color:#d0d0d0; font-size:0.9rem;'>{item}</span>",
                        unsafe_allow_html=True)
        with c2:
            val = st.slider(
                label=item,
                min_value=0,
                max_value=100,
                value=st.session_state[state_key].get(item, 0),
                step=1,
                key=f"{key_prefix}_{item}",
                label_visibility="collapsed",
            )
            updated[item] = val
        with c3:
            total = max(sum(updated.get(i, st.session_state[state_key].get(i, 0)) for i in items), 1)
            pct = round(val / total * 100) if total > 0 else 0
            st.markdown(f"<span style='color:#f0a040; font-weight:600;'>{pct}%</span>",
                        unsafe_allow_html=True)
        with c4:
            total_runs = st.session_state.get("total_runs", 10)
            count = round(val / max(sum(updated.get(i, st.session_state[state_key].get(i, 0)) for i in items), 1) * total_runs)
            st.markdown(f"<span style='color:#666; font-size:0.8rem;'>{count}</span>",
                        unsafe_allow_html=True)

    st.session_state[state_key] = updated

    if st.button(f"Reset Even", key=f"{key_prefix}_reset"):
        even = round(100 / len(items))
        reset_dist = {item: even for item in items}
        diff = 100 - sum(reset_dist.values())
        reset_dist[items[0]] += diff
        st.session_state[state_key] = reset_dist
        st.rerun()

    return updated


# ---------------------------------------------------------------------------
# CycleDeck — guarantees every category is hit proportionally before repeating
# ---------------------------------------------------------------------------
_STATE_FILE = os.path.join(PROJECT_DIR, "output", ".distribution_state.json")


class CycleDeck:
    """Card-deck distribution: builds a shuffled deck proportional to weights,
    deals from the top.  When the deck empties it rebuilds.  This guarantees
    exact proportional coverage over each full cycle — no category is starved
    even across many small batches.

    State persists to disk so it survives process restarts (sandbox mode).
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
        # fix rounding to hit cycle_size exactly
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

    def update_weights(self, weights: dict[str, float]):
        self.weights = weights
        # deck drains naturally; next rebuild uses new weights


def _save_deck_state(decks: dict[str, CycleDeck]):
    """Persist remaining deck cards so they survive restarts."""
    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
    state = {name: deck.deck for name, deck in decks.items()}
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f)


def _load_deck_state() -> dict[str, list[str]]:
    """Load persisted deck state if available."""
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


# ---------------------------------------------------------------------------
# Query dedup — avoids repeating the same query within a rolling window
# ---------------------------------------------------------------------------
_recent_queries: collections.deque = collections.deque(maxlen=45)  # ~3 cycles worth


def _pick_query(domain: str) -> str:
    """Pick a query for the domain, avoiding recent repeats."""
    pool = _DOMAIN_QUERIES.get(domain, _DOMAIN_QUERIES["AI/ML"])
    # Try to find one not recently used
    available = [q for q in pool if q not in _recent_queries]
    if not available:
        # All used recently — pick least-recently-used by just using full pool
        available = pool
    pick = random.choice(available)
    _recent_queries.append(pick)
    return pick


def generate_profile(
    profile_id: str,
    domain: str,
    persona_name: str,
    research_type_name: str,
) -> QueryProfile:
    """Generate a synthetic QueryProfile for a run."""
    query = _pick_query(domain)
    return QueryProfile(
        id=profile_id,
        query=query,
        research_type=_RESEARCH_TYPE_MAP[research_type_name],
        domain=domain,
        complexity=random.choice(_COMPLEXITY_OPTIONS),
        time_sensitivity=random.choice(_TIME_OPTIONS),
        requester_persona=_PERSONA_MAP[persona_name],
        depth_preference=random.choice(_DEPTH_OPTIONS),
    )


def run_single_session(profile: QueryProfile) -> dict:
    """Run one research session, return summary dict."""
    agent = ResearchAgent(profile=profile, verbose=False)
    trace = agent.run_session()
    return {
        "profile_id": trace.profile_id,
        "domain": profile.domain,
        "persona": profile.requester_persona.value,
        "research_type": profile.research_type.value,
        "turns": len(trace.turns),
        "tool_calls": len(trace.tool_calls),
        "tokens": trace.total_tokens,
        "duration": trace.duration,
        "trace": trace,
    }


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------
st.markdown('<div class="main-header">Deep Research Agent</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Control panel for agent trace generation</div>', unsafe_allow_html=True)

# Top controls
col_runs, col_conc, col_spacer = st.columns([1, 1, 6])
with col_runs:
    st.markdown("<div class='input-label'>Total Runs</div>", unsafe_allow_html=True)
    total_runs = st.number_input("Total Runs", min_value=1, max_value=100, value=10,
                                  step=1, label_visibility="collapsed", key="total_runs")
with col_conc:
    st.markdown("<div class='input-label'>Concurrency</div>", unsafe_allow_html=True)
    concurrency = st.number_input("Concurrency", min_value=1, max_value=10, value=3,
                                   step=1, label_visibility="collapsed", key="concurrency")

st.markdown("<br>", unsafe_allow_html=True)

# Distribution cards
domain_dist = render_distribution_card("RESEARCH DOMAIN", RESEARCH_DOMAINS, "domain")
st.markdown("<br>", unsafe_allow_html=True)
sentiment_dist = render_distribution_card("REQUESTER PERSONA", REQUESTER_SENTIMENTS, "persona")
st.markdown("<br>", unsafe_allow_html=True)
type_dist = render_distribution_card("RESEARCH TYPE", RESEARCH_TYPES, "rtype")

st.markdown("<br>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Run button and execution
# ---------------------------------------------------------------------------
run_clicked = st.button(
    f"Run {total_runs} Conversations",
    key="run_btn",
    use_container_width=True,
)

if run_clicked:
    # Build cycle decks (restore persisted state if available)
    saved = _load_deck_state()
    domain_deck = CycleDeck("domain", domain_dist, cycle_size=max(total_runs * 6, 60))
    persona_deck = CycleDeck("persona", sentiment_dist, cycle_size=max(total_runs * 6, 60))
    type_deck = CycleDeck("rtype", type_dist, cycle_size=max(total_runs * 6, 60))
    # Restore leftover cards from previous batches
    if "domain" in saved:
        domain_deck.deck = [c for c in saved["domain"] if c in domain_dist]
    if "persona" in saved:
        persona_deck.deck = [c for c in saved["persona"] if c in sentiment_dist]
    if "rtype" in saved:
        type_deck.deck = [c for c in saved["rtype"] if c in type_dist]

    decks = {"domain": domain_deck, "persona": persona_deck, "rtype": type_deck}

    # Draw from decks — guaranteed proportional coverage across batches
    domains = domain_deck.draw(total_runs)
    personas = persona_deck.draw(total_runs)
    research_types = type_deck.draw(total_runs)

    profiles = []
    for i in range(total_runs):
        pid = f"run_{uuid.uuid4().hex[:8]}"
        profiles.append(generate_profile(pid, domains[i], personas[i], research_types[i]))

    # Progress display
    progress_placeholder = st.empty()
    stats_placeholder = st.empty()
    results_placeholder = st.empty()

    completed = []
    failed = 0
    total_tokens = 0
    total_tools = 0
    total_turns = 0

    # Actual distribution tracking
    actual_domains: dict[str, int] = {}
    actual_personas: dict[str, int] = {}
    actual_types: dict[str, int] = {}

    def update_progress():
        done = len(completed)
        pct = round(done / total_runs * 100)
        status = "Done!" if done == total_runs else "Running..."

        progress_placeholder.markdown(f"""
        <div class="progress-card">
            <div class="progress-title">PROGRESS
                <span style="float:right; color:#888; font-weight:400; text-transform:none; letter-spacing:0;">
                    {"Complete. Check your Judgment dashboard." if done == total_runs else f"Running {done}/{total_runs}..."}
                </span>
            </div>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width:{pct}%;">
                    {done} / {total_runs} — {status}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if completed:
            avg_tools = total_tools / len(completed)
            avg_turns = total_turns / len(completed)
            stats_placeholder.markdown(f"""
            <div style="margin-top:12px;">
                <div class="stats-row">
                    <span>Tools/conv: <strong>{avg_tools:.1f}</strong></span>
                    <span>Turns/conv: <strong>{avg_turns:.1f}</strong></span>
                    <span>Failed: <strong>{failed}</strong></span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        if done == total_runs:
            # Show actual distributions
            domain_str = "".join(f"<div class='actual-col-item'>{k}: {v} ({round(v/total_runs*100)}%)</div>"
                                  for k, v in sorted(actual_domains.items()))
            persona_str = "".join(f"<div class='actual-col-item'>{k}: {v} ({round(v/total_runs*100)}%)</div>"
                                   for k, v in sorted(actual_personas.items()))
            type_str = "".join(f"<div class='actual-col-item'>{k}: {v} ({round(v/total_runs*100)}%)</div>"
                                for k, v in sorted(actual_types.items()))

            results_placeholder.markdown(f"""
            <div class="actual-results">
                <div class="actual-col">
                    <div class="actual-col-title">REQUESTER PERSONA (ACTUAL)</div>
                    {persona_str}
                </div>
                <div class="actual-col">
                    <div class="actual-col-title">RESEARCH TYPE (ACTUAL)</div>
                    {type_str}
                </div>
                <div class="actual-col">
                    <div class="actual-col-title">RESEARCH DOMAIN (ACTUAL)</div>
                    {domain_str}
                </div>
            </div>
            """, unsafe_allow_html=True)

    update_progress()

    # Execute sessions
    if concurrency <= 1:
        for profile in profiles:
            try:
                result = run_single_session(profile)
                completed.append(result)
                total_tokens += result["tokens"]
                total_tools += result["tool_calls"]
                total_turns += result["turns"]
                actual_domains[result["domain"]] = actual_domains.get(result["domain"], 0) + 1
                actual_personas[result["persona"]] = actual_personas.get(result["persona"], 0) + 1
                actual_types[result["research_type"]] = actual_types.get(result["research_type"], 0) + 1
            except Exception as e:
                failed += 1
            update_progress()
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(run_single_session, p): p for p in profiles}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    completed.append(result)
                    total_tokens += result["tokens"]
                    total_tools += result["tool_calls"]
                    total_turns += result["turns"]
                    actual_domains[result["domain"]] = actual_domains.get(result["domain"], 0) + 1
                    actual_personas[result["persona"]] = actual_personas.get(result["persona"], 0) + 1
                    actual_types[result["research_type"]] = actual_types.get(result["research_type"], 0) + 1
                except Exception as e:
                    failed += 1
                update_progress()

    # Persist deck state so next batch continues the cycle
    _save_deck_state(decks)

    # Flush traces
    tracer = get_tracer()
    if tracer:
        flush()

    # Save traces
    output_dir = os.path.join(PROJECT_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    for result in completed:
        trace = result["trace"]
        filepath = os.path.join(output_dir, f"trace_{trace.profile_id}.json")
        with open(filepath, "w") as f:
            f.write(trace.model_dump_json(indent=2))

    update_progress()
