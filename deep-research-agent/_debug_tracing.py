#!/usr/bin/env python3
"""Debug script to test judgeval import and tracing inside Modal container."""
import sys
import os

print("=== ENVIRONMENT DEBUG ===")
print(f"Python: {sys.version}")
print(f"sys.path: {sys.path}")
print()

# 1. Test judgeval import
print("--- judgeval import ---")
try:
    import judgeval
    print(f"OK: judgeval {judgeval.__version__}")
except ImportError as e:
    print(f"ImportError: {e}")
except Exception as e:
    print(f"Other error: {type(e).__name__}: {e}")

print()

# 2. Show relevant env vars
print("--- env vars (before remap) ---")
for k in sorted(os.environ):
    kl = k.lower()
    if any(x in kl for x in ["judgment", "anthropic", "gemini", "org_id"]):
        val = os.environ[k]
        print(f"  {k} = {val[:15]}...")

print()

# 3. Remap env vars
aliases = {
    "ANTHROPIC_API_KEY": ["Research_Agent_Anthropic_Key"],
    "GEMINI_API_KEY": ["Gemini_key"],
    "JUDGMENT_API_KEY": ["Judgment_API_Key"],
    "JUDGMENT_ORG_ID": ["Judgment_internal_agent_org_id"],
}
for canonical, alts in aliases.items():
    if not os.environ.get(canonical):
        for alt in alts:
            val = os.environ.get(alt)
            if val:
                os.environ[canonical] = val
                print(f"  Remapped {alt} -> {canonical}")
                break

print()
print("--- env vars (after remap) ---")
print(f"  ANTHROPIC_API_KEY set: {bool(os.environ.get('ANTHROPIC_API_KEY'))}")
print(f"  GEMINI_API_KEY set: {bool(os.environ.get('GEMINI_API_KEY'))}")
print(f"  JUDGMENT_API_KEY set: {bool(os.environ.get('JUDGMENT_API_KEY'))}")
print(f"  JUDGMENT_ORG_ID set: {bool(os.environ.get('JUDGMENT_ORG_ID'))}")

print()

# 4. Test tracing init
print("--- tracing init ---")
sys.path.insert(0, "/app")
try:
    from tracing import get_tracer, _ensure_init, _tracer, _initialized
    print(f"  _initialized before: {_initialized}")
    tracer = get_tracer()
    print(f"  tracer: {tracer}")
    print(f"  tracer type: {type(tracer)}")
    if tracer is None:
        print("  TRACING IS DISABLED - investigating...")
        # Try manual init
        api_key = os.environ.get("JUDGMENT_API_KEY")
        print(f"  JUDGMENT_API_KEY value: {api_key[:15] if api_key else 'NOT SET'}...")
        if api_key:
            from judgeval import Judgeval
            print("  Judgeval class imported OK")
            jclient = Judgeval(project_name="debug-test")
            print(f"  Judgeval client created: {jclient}")
            t = jclient.tracer.create()
            print(f"  Tracer created manually: {t}")
    else:
        print("  TRACING IS WORKING!")
except Exception as e:
    import traceback
    print(f"  Exception: {type(e).__name__}: {e}")
    traceback.print_exc()

print()
print("=== DONE ===")
