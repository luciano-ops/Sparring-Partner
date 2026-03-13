"""Lab result interpreter — compares values to reference ranges and detects patterns."""

from __future__ import annotations

import json
from pathlib import Path

_DATA_PATH = Path(__file__).parent.parent / "data" / "lab_panels.json"
_PANELS = None


def _load_panels():
    global _PANELS
    if _PANELS is None:
        with open(_DATA_PATH) as f:
            _PANELS = json.load(f)["panels"]
    return _PANELS


def _normalize_test_name(name: str) -> str:
    return name.lower().strip().replace(" ", "")


def _find_test_ref(test_name: str, panels: dict) -> tuple[dict | None, str | None]:
    """Find reference data for a test name across all panels."""
    norm = _normalize_test_name(test_name)
    for panel_key, panel in panels.items():
        for test in panel["tests"]:
            if _normalize_test_name(test["name"]) == norm or _normalize_test_name(test["full_name"]) == norm:
                return test, panel_key
    # Fuzzy match — check if test name is contained in any full name
    for panel_key, panel in panels.items():
        for test in panel["tests"]:
            if norm in _normalize_test_name(test["full_name"]) or _normalize_test_name(test["full_name"]) in norm:
                return test, panel_key
    return None, None


def _classify_value(value: float, ref: dict) -> dict:
    """Classify a lab value as normal, low, high, or critical."""
    result = {"status": "normal", "severity": "normal"}

    critical_low = ref.get("critical_low")
    critical_high = ref.get("critical_high")
    ref_low = ref.get("ref_low")
    ref_high = ref.get("ref_high")

    if critical_low is not None and value < critical_low:
        result = {"status": "critically_low", "severity": "critical"}
    elif critical_high is not None and value > critical_high:
        result = {"status": "critically_high", "severity": "critical"}
    elif ref_low is not None and value < ref_low:
        result = {"status": "low", "severity": "abnormal"}
    elif ref_high is not None and value > ref_high:
        result = {"status": "high", "severity": "abnormal"}

    return result


def _detect_patterns(interpreted_results: list[dict], panels: dict) -> list[dict]:
    """Look for clinically meaningful patterns across results."""
    # Build a map of test_name -> status
    status_map = {}
    for r in interpreted_results:
        status_map[r["test_name"]] = r["classification"]["status"]

    detected = []
    for panel_key, panel in panels.items():
        for pattern in panel.get("patterns", []):
            indicators = pattern["indicators"]
            match = True
            for test_name, expected in indicators.items():
                actual = status_map.get(test_name)
                if actual is None:
                    match = False
                    break
                if expected == "abnormal":
                    if actual == "normal":
                        match = False
                        break
                elif expected == "present":
                    if actual == "normal":
                        match = False
                        break
                elif expected in ("below_7", "above_9"):
                    # Special A1C handling
                    val = next((r["value"] for r in interpreted_results if r["test_name"] == test_name), None)
                    if val is None:
                        match = False
                        break
                    if expected == "below_7" and val >= 7:
                        match = False
                        break
                    if expected == "above_9" and val <= 9:
                        match = False
                        break
                elif expected in ("high", "low"):
                    if expected not in actual:
                        match = False
                        break

            if match:
                detected.append({
                    "pattern": pattern["name"],
                    "description": pattern["description"],
                    "involved_tests": list(indicators.keys()),
                })

    return detected


def interpret_labs(
    lab_values: list[dict],
    patient_age: int | None = None,
    patient_sex: str | None = None,
) -> dict:
    """Interpret lab results against reference ranges and detect patterns."""
    panels = _load_panels()
    interpreted = []
    unknown_tests = []
    has_critical = False

    for lab in lab_values:
        test_name = lab["test"]
        value = lab["value"]
        unit = lab.get("unit", "")

        ref, panel_key = _find_test_ref(test_name, panels)
        if ref is None:
            unknown_tests.append(test_name)
            continue

        classification = _classify_value(value, ref)
        if classification["severity"] == "critical":
            has_critical = True

        interpreted.append({
            "test_name": ref["name"],
            "full_name": ref["full_name"],
            "value": value,
            "unit": ref.get("unit", unit),
            "reference_range": f"{ref.get('ref_low', '?')} - {ref.get('ref_high', '?')}",
            "classification": classification,
            "panel": panel_key,
            "what_it_measures": ref["what_it_measures"],
            "interpretation": ref["high_meaning"] if "high" in classification["status"] else ref["low_meaning"] if "low" in classification["status"] else "Within normal range",
        })

    patterns = _detect_patterns(interpreted, panels)

    abnormal_count = sum(1 for r in interpreted if r["classification"]["status"] != "normal")
    normal_count = sum(1 for r in interpreted if r["classification"]["status"] == "normal")

    return {
        "results": interpreted,
        "patterns_detected": patterns,
        "summary": {
            "total_tests": len(interpreted),
            "normal": normal_count,
            "abnormal": abnormal_count,
            "has_critical_values": has_critical,
        },
        "unknown_tests": unknown_tests,
        "note": "Lab interpretation should be reviewed by your healthcare provider in the context of your full medical history.",
    }
