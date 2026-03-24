# Health Agent → Modal Deployment Prompt

Paste everything below this line into your health agent Claude chat:

---

I need you to deploy my **health agent** app to Modal, following the exact same pattern as my legal-agent deployment that's already working. I'll give you all the reference code and context so you can do this without any additional info from me.

## REFERENCE: Working Legal Agent Modal Deployment (follow this pattern exactly)

This is my working `modal_legal.py` — adapt this architecture for the health agent:

```python
"""Modal app for legal research agent -- synthetic evaluation sandbox."""

from __future__ import annotations

import collections
import json
import random
import uuid as _uuid
from typing import Optional

import modal

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

_ENV_ALIASES = {
    "ANTHROPIC_API_KEY": ["ANTHROPIC_API_KEY", "Legal_Agent_Anthropic_Key"],
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


class CycleDeck:
    """Card-deck distribution: builds a shuffled deck proportional to weights,
    deals from the top. When the deck empties it rebuilds."""
    def __init__(self, name, weights, cycle_size=60):
        self.name = name
        self.weights = weights
        self.cycle_size = max(cycle_size, len(weights) * 2)
        self.deck = []
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
        diff = self.cycle_size - sum(counts.values())
        sorted_items = sorted(items, key=lambda x: counts[x], reverse=(diff < 0))
        for i in range(abs(diff)):
            counts[sorted_items[i % len(sorted_items)]] += 1 if diff > 0 else -1
        self.deck = []
        for item in items:
            self.deck.extend([item] * max(counts[item], 0))
        random.shuffle(self.deck)

    def draw(self, n):
        result = []
        while len(result) < n:
            if not self.deck:
                self._rebuild()
            take = min(n - len(result), len(self.deck))
            result.extend(self.deck[:take])
            self.deck = self.deck[take:]
        return result
```

Key patterns from the legal deployment:
- `_ensure_env_vars()` called at the top of every worker function
- `sys.path.insert(0, "/app")` at the top of every worker function
- `wrap_returned_exceptions=False` on `.map()` calls
- `results_volume.commit()` after writing to volume
- `flush_and_shutdown()` before container exits
- Debug tracing function for `--count 0`
- CycleDeck for proportional distribution
- Cron with ramp-up schedule
- Deck state persistence to volume

## CRITICAL ARCHITECTURE DIFFERENCES — Health Agent vs Legal Agent

The health agent has significant differences you MUST handle:

### 1. Instrumentation (MUST CHANGE)
The health agent uses `instrumentation.py` which does **direct, non-lazy** Judgeval init:
```python
from judgeval import Judgeval
judgeval_client = Judgeval(project_name="Internal-Health-Agent")
tracer = judgeval_client.tracer.create()
```

This will **crash** if `judgeval` isn't installed or env vars are missing. For Modal, you MUST replace this with the **lazy/no-op tracing.py pattern** from the legal agent (safe init, fallback to no-op):

```python
"""Judgment SDK tracing -- optional, no-op when credentials are missing."""
import atexit, functools, os

_tracer = None
_initialized = False

def _ensure_init():
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
        print("[tracing] judgeval package not installed -- tracing disabled")
        return
    try:
        jclient = Judgeval(project_name="Internal-Health-Agent")
        _tracer = jclient.tracer.create()
        atexit.register(_atexit_flush)
    except Exception as exc:
        print(f"[tracing] Judgment SDK init failed: {type(exc).__name__}: {exc}")

def _atexit_flush():
    if _tracer is not None:
        try:
            _tracer.force_flush(timeout_millis=10_000)
            _tracer.shutdown(timeout_millis=5_000)
        except Exception:
            pass

def get_tracer():
    _ensure_init()
    return _tracer

def flush():
    if _tracer is None:
        return
    try:
        _tracer.force_flush(timeout_millis=15_000)
    except Exception as exc:
        print(f"[tracing] flush error: {exc}")

def flush_and_shutdown():
    if _tracer is None:
        return
    try:
        _tracer.force_flush(timeout_millis=15_000)
        _tracer.shutdown(timeout_millis=5_000)
    except Exception as exc:
        print(f"[tracing] flush/shutdown error: {exc}")

def observe(span_type="function"):
    def decorator(func):
        _cache = {}
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if "fn" not in _cache:
                t = get_tracer()
                _cache["fn"] = t.observe(span_type=span_type)(func) if t else None
            observed = _cache["fn"]
            if observed is not None:
                return observed(*args, **kwargs)
            return func(*args, **kwargs)
        return wrapper
    return decorator

def wrap_client(client_instance):
    _ensure_init()
    t = _tracer
    if t is None:
        return client_instance
    try:
        return t.wrap(client_instance)
    except Exception:
        return client_instance
```

### 2. Tools are in a subdirectory with data files
The health agent has a `tools/` package and a `data/` directory:
- `tools/__init__.py` — imports from submodules, wraps with `tracer.observe()`
- `tools/symptom_db.py` — loads `data/conditions.json`
- `tools/lab_interpreter.py` — loads `data/lab_panels.json`
- `tools/drug_checker.py` — loads `data/interactions.json`
- `tools/triage.py`, `tools/intake.py`, `tools/risk_calculator.py`, `tools/guidelines.py`, `tools/medication_info.py`, `tools/preventive_care.py`, `tools/care_plan.py`

For Modal, you need to:
- Copy the entire `tools/` directory and `data/` directory into the image
- Fix `tools/__init__.py` to use the lazy tracing pattern instead of direct `from instrumentation import tracer`
- Fix data file paths (they use `Path(__file__).parent.parent / "data"` which needs to resolve correctly in `/app/`)

### 3. System prompt loaded from file
`agent.py` loads from `prompts/system.md`:
```python
SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text()
```
You need to copy `prompts/system.md` into the image too.

### 4. Main agent is Claude Haiku 4.5 (not Sonnet)
```python
model: str = "claude-haiku-4-5-20251001"
```

### 5. Tools are deterministic Python (not LLM-generated)
Unlike the legal agent where tools call Haiku to generate results, the health agent tools are deterministic Python functions using local JSON data files. No Haiku calls in tools. This means:
- No `_call_haiku()` or `tools_degraded` pattern needed
- The `token_tracker` in tools.py doesn't exist in the health agent
- Tool imports come from the `tools/` package, not a single `tools.py` file

### 6. Prompt caching
The health agent uses prompt caching for cost efficiency:
```python
_SYSTEM_BLOCKS = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
_CACHED_TOOLS = [*TOOL_DEFINITIONS[:-1], {**TOOL_DEFINITIONS[-1], "cache_control": {"type": "ephemeral"}}]
```

### 7. Patient profiles from generator
The health agent has 1050+ pre-generated profiles in `profiles/generator.py`. For Modal, you should generate profiles inline (like the legal agent does) rather than loading from the JSON file.

### 8. run.py uses `tracer` directly
```python
from instrumentation import tracer
@tracer.observe(span_type="function")
def run_conversation(...)
```
This needs to be adapted to use the lazy tracing pattern.

## HEALTH AGENT SOURCE FILES

### models.py
```python
from __future__ import annotations
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

class CommunicationStyle(str, Enum):
    MEDICAL_LITERATE = "medical_literate"
    VAGUE = "vague"
    ANXIOUS = "anxious"
    MATTER_OF_FACT = "matter_of_fact"
    RAMBLING = "rambling"

class AgentMode(str, Enum):
    TRIAGE = "triage"
    INTAKE = "intake"
    LAB_REVIEW = "lab_review"

class UrgencyLevel(int, Enum):
    EMERGENCY = 1
    URGENT = 2
    SEMI_URGENT = 3
    ROUTINE = 4
    SELF_CARE = 5

class Allergy(BaseModel):
    allergen: str
    reaction: str

class Vitals(BaseModel):
    bp: Optional[str] = None
    hr: Optional[int] = None
    temp: Optional[float] = None
    bg: Optional[int] = None
    spo2: Optional[int] = None

class LabValue(BaseModel):
    test: str
    value: float
    unit: str

class PatientProfile(BaseModel):
    id: str
    age: int
    sex: str
    mode: AgentMode
    chief_complaint: str
    communication_style: CommunicationStyle
    medications: list[str] = Field(default_factory=list)
    allergies: list[Allergy] = Field(default_factory=list)
    medical_history: list[str] = Field(default_factory=list)
    family_history: list[str] = Field(default_factory=list)
    social: dict[str, str] = Field(default_factory=dict)
    vitals: Optional[Vitals] = None
    labs: Optional[list[LabValue]] = None
    opening_message: str
    expected_urgency: Optional[int] = None
    red_flags_present: list[str] = Field(default_factory=list)
    edge_case_tags: list[str] = Field(default_factory=list)

class ToolCall(BaseModel):
    tool: str
    input: dict
    output: dict

class ConversationTurn(BaseModel):
    role: str
    content: str

class Trace(BaseModel):
    profile_id: str
    mode: AgentMode
    turns: list[ConversationTurn] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    final_urgency: Optional[int] = None
    metadata: dict = Field(default_factory=dict)
```

### agent.py (current — needs adaptation for Modal)
```python
"""Core health agent — agentic tool loop powered by Claude."""

from __future__ import annotations

import json
import time
from pathlib import Path
from models import Trace, ConversationTurn, ToolCall, AgentMode
from tools import TOOL_DEFINITIONS, execute_tool
from instrumentation import get_wrapped_client

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text()

_SYSTEM_BLOCKS = [
    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
]

_CACHED_TOOLS = [
    *TOOL_DEFINITIONS[:-1],
    {**TOOL_DEFINITIONS[-1], "cache_control": {"type": "ephemeral"}},
]

_BOILERPLATE_KEYS = {
    "self_care_recommendations",
    "warning_signs_seek_immediate_care",
    "questions_for_next_visit",
}

_MAX_TOOL_RESULT_CHARS = 2000

def _compact_tool_result(result: dict) -> str:
    compact = {k: v for k, v in result.items() if k not in _BOILERPLATE_KEYS}
    serialized = json.dumps(compact, default=str)
    if len(serialized) > _MAX_TOOL_RESULT_CHARS:
        serialized = serialized[:_MAX_TOOL_RESULT_CHARS] + '…"}'
    return serialized


class HealthAgent:
    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.client = get_wrapped_client()
        self.model = model
        self.messages: list[dict] = []
        self.trace = Trace(profile_id="", mode=AgentMode.TRIAGE)
        self._turn_count = 0

    def reset(self, profile_id: str, mode: AgentMode):
        self.messages = []
        self.trace = Trace(profile_id=profile_id, mode=mode)
        self._turn_count = 0

    def run_turn(self, user_message: str) -> str:
        self.messages.append({"role": "user", "content": user_message})
        self.trace.turns.append(ConversationTurn(role="user", content=user_message))
        self._turn_count += 1
        max_tool_rounds = 10
        tool_round = 0
        while tool_round < max_tool_rounds:
            t0 = time.time()
            response = self.client.messages.create(
                model=self.model, max_tokens=4096,
                system=_SYSTEM_BLOCKS, tools=_CACHED_TOOLS,
                messages=self.messages,
            )
            latency = time.time() - t0
            usage = response.usage
            self.trace.metadata.setdefault("api_calls", []).append({
                "turn": self._turn_count, "tool_round": tool_round,
                "model": self.model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
                "latency_s": round(latency, 3),
                "stop_reason": response.stop_reason,
            })
            self.messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = execute_tool(block.name, block.input)
                        self.trace.tool_calls.append(ToolCall(
                            tool=block.name, input=block.input, output=result,
                        ))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": _compact_tool_result(result),
                        })
                self.messages.append({"role": "user", "content": tool_results})
                tool_round += 1
            else:
                text_parts = []
                for block in response.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
                text = "".join(text_parts)
                self.trace.turns.append(ConversationTurn(role="assistant", content=text))
                return text

        fallback = "I apologize, but I'm having difficulty processing your request. Please consult a healthcare provider directly."
        self.trace.turns.append(ConversationTurn(role="assistant", content=fallback))
        return fallback

    def is_wrapping_up(self, response: str) -> bool:
        wrap_signals = [
            "take care", "don't hesitate to reach out", "wishing you",
            "hope this helps", "feel free to come back",
            "PATIENT INTAKE SUMMARY", "recommended action:",
            "urgency level:", "in summary", "to summarize",
        ]
        lower = response.lower()
        return any(signal in lower for signal in wrap_signals)

    def get_trace(self) -> Trace:
        calls = self.trace.metadata.get("api_calls", [])
        self.trace.metadata["total_input_tokens"] = sum(c["input_tokens"] for c in calls)
        self.trace.metadata["total_output_tokens"] = sum(c["output_tokens"] for c in calls)
        self.trace.metadata["total_latency_s"] = round(sum(c["latency_s"] for c in calls), 3)
        self.trace.metadata["total_turns"] = self._turn_count
        self.trace.metadata["total_tool_calls"] = len(self.trace.tool_calls)
        self.trace.metadata["tools_used"] = list({tc.tool for tc in self.trace.tool_calls})
        cache_created = sum(c.get("cache_creation_input_tokens", 0) for c in calls)
        cache_read = sum(c.get("cache_read_input_tokens", 0) for c in calls)
        self.trace.metadata["cache_creation_input_tokens"] = cache_created
        self.trace.metadata["cache_read_input_tokens"] = cache_read
        if cache_read > 0:
            self.trace.metadata["estimated_cache_savings_tokens"] = int(cache_read * 0.9)
        return self.trace
```

### patient_simulator.py (current — Gemini-powered)
```python
"""Patient simulator — uses Gemini Flash to play the patient side."""

from __future__ import annotations
import hashlib
from google import genai
from models import PatientProfile

def _build_patient_system_prompt(profile: PatientProfile) -> str:
    # [builds comprehensive system prompt with communication styles,
    #  emotional arcs (Frustrated/Anxious/Reassured/Still Anxious via MD5 hash),
    #  patient profile details, and conversation rules]
    # ... (full implementation in the file, preserving all style instructions and arcs)

class PatientSimulator:
    def __init__(self, profile: PatientProfile):
        self.profile = profile
        self.client = genai.Client()  # reads GEMINI_API_KEY from env
        self.system_prompt = _build_patient_system_prompt(profile)
        self.history: list[dict] = []

    def get_opening_message(self) -> str:
        return self.profile.opening_message

    def respond(self, agent_message: str) -> str:
        self.history.append({
            "role": "user",
            "parts": [{"text": f"[Health Assistant says]: {agent_message}\n\nRespond as the patient."}],
        })
        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=self.history,
            config={"system_instruction": self.system_prompt, "max_output_tokens": 300},
        )
        reply = response.text
        self.history.append({"role": "model", "parts": [{"text": reply}]})
        return reply
```

### tools/__init__.py (current — needs adaptation)
```python
"""Tool definitions and dispatch for the health agent."""
import functools
from .symptom_db import symptom_lookup
from .lab_interpreter import interpret_labs
from .drug_checker import drug_interaction_check
from .triage import classify_urgency
from .intake import generate_intake_summary
from .risk_calculator import calculate_risk_score
from .guidelines import check_guidelines
from .medication_info import lookup_medication_info
from .preventive_care import check_preventive_care
from .care_plan import generate_care_plan
from instrumentation import tracer  # THIS MUST CHANGE to lazy tracing

def _traced_tool(name, fn):
    @tracer.observe(span_name=name, span_type="tool")  # THIS MUST CHANGE
    @functools.wraps(fn)
    def wrapper(**kwargs):
        return fn(**kwargs)
    return wrapper

TOOL_DEFINITIONS = [
    # 10 tool definitions:
    # symptom_lookup, interpret_labs, drug_interaction_check, classify_urgency,
    # generate_intake_summary, calculate_risk_score, check_guidelines,
    # lookup_medication_info, check_preventive_care, generate_care_plan
    # (full definitions in the file — preserve all 10 exactly)
]

_RAW_TOOLS = {
    "symptom_lookup": symptom_lookup,
    "interpret_labs": interpret_labs,
    "drug_interaction_check": drug_interaction_check,
    "classify_urgency": classify_urgency,
    "generate_intake_summary": generate_intake_summary,
    "calculate_risk_score": calculate_risk_score,
    "check_guidelines": check_guidelines,
    "lookup_medication_info": lookup_medication_info,
    "check_preventive_care": check_preventive_care,
    "generate_care_plan": generate_care_plan,
}

TOOL_MAP = {name: _traced_tool(name, fn) for name, fn in _RAW_TOOLS.items()}

def execute_tool(name, input_data):
    handler = TOOL_MAP.get(name)
    if not handler:
        return {"error": f"Unknown tool: {name}"}
    try:
        return handler(**input_data)
    except Exception as e:
        return {"error": f"Tool execution failed: {str(e)}"}
```

### Tool data files
The tools load JSON data from `data/` directory:
- `data/conditions.json` (~20KB, 384 lines) — symptom→condition database
- `data/interactions.json` (~11KB, 229 lines) — drug interaction database
- `data/lab_panels.json` (~16KB, 99 lines) — lab reference ranges and patterns

These must be copied into the Modal image at `/app/data/`.

### profiles/generator.py
Generates 1050 patient profiles with realistic distributions:
- Age brackets weighted by healthcare utilization
- Modes: triage (40%), intake (35%), lab_review (25%)
- Communication styles: matter_of_fact (30%), anxious (25%), vague (20%), medical_literate (15%), rambling (10%)
- 32 triage scenarios with urgency 1-5 (emergency→self-care)
- 12 intake scenarios
- 13 lab review templates with jittered values
- Medications by condition, allergies, family history, social history, vitals
- Stochastic opening messages assembled from random fragments per style

For Modal: embed the profile generation logic in the modal file OR copy `profiles/generator.py` into the image.

### prompts/system.md
Full system prompt defining "Judgment Health" AI health assistant with 3 modes (Patient Intake, Symptom Triage, Lab Review), safety framework, OLDCARTS methodology, 10 tool usage guidelines, and cross-mode behaviors. ~3.5KB. Must be copied into Modal image at `/app/prompts/system.md`.

### run.py (current — needs adaptation)
Key functions:
- `run_conversation()` — decorated with `@tracer.observe(span_type="function")`, sets Judgment metadata (mode, style, age, sex, chief_complaint, expected_urgency, edge_case_tags), runs multi-turn loop, builds conversation transcript for Judgment classifiers
- `_pick_max_turns()` — 15%→3-4, 45%→5-6, 30%→7-8, 10%→9-10
- `_assign_session_ids()` — 70% standalone, 30% grouped in clusters of 2-4

### profile_classifier.py
3 classification dimensions for the Judgment dashboard:
- Clinical Domain: Cardiac, Endocrine, General/Preventive, GI, Mental Health, Musculoskeletal, Neurological, Respiratory
- Patient Sentiment: Frustrated, Anxious, Reassured, Still Anxious (from MD5 hash)
- Interaction Type: Emergency Escalation, History Collection, Lab Interpretation, Medication Review, Preventive Screening, Symptom Assessment, Patient Education

## MODAL ENVIRONMENT

- **Environment**: `internal-agents-l`
- **App name**: `health-agent-eval`
- **Volume**: `health-results`
- **Secrets** (same as legal agent — they share the same Anthropic/Gemini/Judgment keys):
  - `Legal-Agent-Anthropic-Key` — contains `ANTHROPIC_API_KEY` (exposed as `Legal_Agent_Anthropic_Key` by Modal)
  - `Gemini-key` — contains `GEMINI_API_KEY` (exposed as `Gemini_key`)
  - `JudgmentAPI_Key` — contains `JUDGMENT_API_KEY` (exposed as `Judgment_API_Key`)
  - `judgment-org-id` — contains `JUDGMENT_ORG_ID` (exposed as various names)
- Same `_ENV_ALIASES` and `_ensure_env_vars()` pattern as legal agent

## KNOWN GOTCHAS (from legal agent deployment)

1. **`packaging` dependency** — judgeval needs it but doesn't declare it. Add `"packaging"` to pip_install.
2. **tracing.py error handling** — use separate try/except for import and init. The lazy/no-op pattern is mandatory.
3. **Python 3.11** — use `python_version="3.11"` in debian_slim.
4. **`Function.map` deprecation** — use `wrap_returned_exceptions=False` parameter.
5. **Volume commits** — always call `results_volume.commit()` after writing files.
6. **`judgeval.__version__`** — doesn't exist (AttributeError) but cosmetic; tracer still works.
7. **Data file paths** — tools use `Path(__file__).parent.parent / "data"` which must resolve correctly from `/app/tools/` to `/app/data/`.

## CATEGORY DEFINITIONS FOR CycleDeck

Use these dimensions for proportional distribution:

**Clinical Domains** (8):
- Cardiac, Endocrine, General/Preventive, GI, Mental Health, Musculoskeletal, Neurological, Respiratory

**Agent Modes** (3):
- triage (40%), intake (35%), lab_review (25%)

**Communication Styles** (5):
- matter_of_fact (30%), anxious (25%), vague (20%), medical_literate (15%), rambling (10%)

## DOMAIN QUERIES (embed in modal file)

Generate realistic patient scenarios per mode. Use the triage scenarios, intake scenarios, and lab templates from `profiles/generator.py` to create diverse patient profiles. The profile generator already has 32 triage scenarios, 12 intake scenarios, and 13 lab templates with edge cases (emergency, pediatric, mental health, cardiac, polypharmacy).

## WHAT TO CREATE

Create a single `modal_health.py` file at `/Users/lucianoarroyo/test/health-agent/` that:

1. **Creates the Modal app** named `health-agent-eval`
2. **Builds the image** with all files copied in:
   - All Python files: `agent.py`, `models.py`, `patient_simulator.py`, `run.py`, `profile_classifier.py`
   - `tools/` directory (all 11 .py files)
   - `data/` directory (3 JSON files)
   - `prompts/system.md`
   - NEW `tracing.py` (lazy/no-op pattern, project="Internal-Health-Agent")
3. **Adapts agent.py** — change `from instrumentation import get_wrapped_client` to use the lazy `tracing.py` `wrap_client()` instead
4. **Adapts tools/__init__.py** — change `from instrumentation import tracer` to use the lazy tracing pattern for tool spans
5. **Adapts run.py** — change `from instrumentation import tracer` and `@tracer.observe()` to use the lazy pattern
6. **Worker function** `run_single()` — runs one conversation (generates profile, runs agent loop, saves trace)
7. **Orchestrator** `run_batch()` — CycleDeck distribution across modes, styles, clinical domains
8. **Cron** `cron_health()` — every 10 min, trickle traffic with ramp
9. **Debug function** `debug_tracing()` for `--count 0`
10. **Local entrypoint** `main(count, seed)`

Also copy all the source files the modal file needs into `/Users/lucianoarroyo/test/health-agent/`:
- `models.py` (can use as-is)
- `agent.py` (adapted to use `tracing.py` instead of `instrumentation.py`)
- `patient_simulator.py` (can use as-is)
- `tracing.py` (new, lazy/no-op pattern with project="Internal-Health-Agent")
- `profile_classifier.py` (can use as-is)
- `tools/` directory — adapt `__init__.py` to use lazy tracing, keep all 10 tool files as-is
- `data/` directory — copy all 3 JSON files as-is
- `prompts/system.md` — copy as-is
- `requirements.txt`

## STEP-BY-STEP DEPLOYMENT

1. Create all files at `/Users/lucianoarroyo/test/health-agent/`
2. Verify the directory structure looks right
3. Deploy: `cd /Users/lucianoarroyo/test/health-agent && modal deploy modal_health.py --env internal-agents-l`
4. Test tracing: `modal run modal_health.py --env internal-agents-l --count 0`
5. Run 1 real session: `modal run modal_health.py --env internal-agents-l --count 1`
6. Show me the results

The health agent source files are at `/Users/lucianoarroyo/test/judgment-health-agent/`. Copy what you need from there.
