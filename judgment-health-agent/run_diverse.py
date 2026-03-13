"""Run 50 hand-picked diverse profiles to even out the dashboard.

Skips: neutral sentiment, generic intake (annual/wellness/preventive), history-collection-only.
Balances: emotional arcs (frustrated/anxious/reassured/still_anxious), modes (triage/lab_review/intake).

Usage:
    python3.11 run_diverse.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from run import run_batch, load_profiles, PROFILES_PATH

SELECTED_IDS = [
    "patient_0002", "patient_0003", "patient_0004", "patient_0005", "patient_0006",
    "patient_0007", "patient_0009", "patient_0010", "patient_0011", "patient_0013",
    "patient_0014", "patient_0015", "patient_0016", "patient_0017", "patient_0018",
    "patient_0019", "patient_0020", "patient_0021", "patient_0022", "patient_0023",
    "patient_0024", "patient_0025", "patient_0027", "patient_0028", "patient_0029",
    "patient_0030", "patient_0031", "patient_0032", "patient_0033", "patient_0034",
    "patient_0036", "patient_0037", "patient_0038", "patient_0039", "patient_0040",
    "patient_0041", "patient_0044", "patient_0045", "patient_0046", "patient_0047",
    "patient_0048", "patient_0051", "patient_0052", "patient_0059", "patient_0061",
    "patient_0065", "patient_0066", "patient_0067", "patient_0072", "patient_0073",
]


def main():
    from instrumentation import tracer
    import time, json
    from run import OUTPUT_DIR

    all_profiles = load_profiles(PROFILES_PATH)
    id_set = set(SELECTED_IDS)
    profiles = [p for p in all_profiles if p.id in id_set]

    # Preserve the order from SELECTED_IDS
    order = {pid: i for i, pid in enumerate(SELECTED_IDS)}
    profiles.sort(key=lambda p: order[p.id])

    print(f"Running {len(profiles)} diverse profiles (no neutral/general/history-only)")

    traces = run_batch(profiles, concurrency=1, verbose=True)

    if traces:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        trace_file = OUTPUT_DIR / f"traces_diverse_{timestamp}.json"
        trace_file.write_text(json.dumps(traces, indent=2, default=str))
        print(f"\nTraces saved to: {trace_file}")

    print("\nFlushing traces to Judgment...")
    tracer.shutdown(timeout_millis=30000)
    print("Done.")


if __name__ == "__main__":
    main()
