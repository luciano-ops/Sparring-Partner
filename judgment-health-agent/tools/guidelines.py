"""Clinical guidelines lookup — returns evidence-based care recommendations."""

from __future__ import annotations

import random

_GUIDELINES = {
    "hypertension": {
        "condition": "Hypertension",
        "source": "AHA/ACC 2017 Guidelines",
        "key_recommendations": [
            "Stage 1 (130-139/80-89): Lifestyle modification first; if 10-year ASCVD risk >=10%, add medication",
            "Stage 2 (>=140/90): Lifestyle modification + medication (typically 2 agents)",
            "First-line agents: thiazide diuretics, ACE inhibitors, ARBs, or CCBs",
            "Target: <130/80 mmHg for most adults",
        ],
        "lifestyle_modifications": [
            "DASH diet (rich in fruits, vegetables, whole grains)",
            "Sodium restriction (<1500mg/day ideal, <2300mg/day acceptable)",
            "Regular aerobic exercise (90-150 min/week)",
            "Weight loss if overweight (target BMI <25)",
            "Limit alcohol (<=2 drinks/day men, <=1 drink/day women)",
        ],
        "monitoring": "Recheck BP in 1-3 months after initiating treatment. Home BP monitoring recommended.",
        "red_flags_requiring_immediate_action": [
            "BP >180/120 with symptoms (hypertensive emergency)",
            "New headache, vision changes, or chest pain with elevated BP",
        ],
    },
    "diabetes": {
        "condition": "Type 2 Diabetes",
        "source": "ADA Standards of Care 2024",
        "key_recommendations": [
            "A1C target: <7% for most adults (individualize for elderly/comorbidities)",
            "First-line: Metformin + lifestyle modification",
            "If A1C >9%: Consider dual therapy or insulin from start",
            "Add GLP-1 RA or SGLT2 inhibitor if cardiovascular or renal risk",
            "Annual comprehensive foot exam, eye exam, kidney function panel",
        ],
        "lifestyle_modifications": [
            "Medical nutrition therapy with registered dietitian",
            "150+ min/week moderate-intensity physical activity",
            "Weight management (5-7% loss if overweight)",
            "Diabetes self-management education and support (DSMES)",
        ],
        "monitoring": "A1C every 3-6 months. Self-monitoring of blood glucose as indicated.",
        "red_flags_requiring_immediate_action": [
            "Blood glucose >300 mg/dL with symptoms",
            "Signs of DKA: nausea, vomiting, abdominal pain, fruity breath",
            "Hypoglycemia <54 mg/dL or loss of consciousness",
        ],
    },
    "chest_pain": {
        "condition": "Acute Chest Pain Evaluation",
        "source": "AHA/ACC 2021 Chest Pain Guideline",
        "key_recommendations": [
            "Use HEART score for risk stratification in low-to-intermediate risk",
            "High-risk features: ongoing pain, hemodynamic instability, ECG changes",
            "Low-risk patients: consider stress testing or coronary CTA",
            "Troponin testing: serial measurements at 0 and 3-6 hours",
            "Consider non-cardiac causes: GERD, musculoskeletal, anxiety",
        ],
        "lifestyle_modifications": [],
        "monitoring": "Serial troponin, continuous cardiac monitoring if intermediate/high risk.",
        "red_flags_requiring_immediate_action": [
            "STEMI criteria on ECG — immediate catheterization",
            "Hemodynamic instability (hypotension, shock)",
            "Acute aortic dissection signs (tearing pain, BP differential)",
        ],
    },
    "headache": {
        "condition": "Headache Evaluation",
        "source": "AAN Practice Guidelines",
        "key_recommendations": [
            "Distinguish primary (migraine, tension, cluster) from secondary headaches",
            "SNOOP red flags: Systemic symptoms, Neurologic signs, Onset sudden, Older age >50, Pattern change",
            "Neuroimaging for: thunderclap headache, new neurologic deficit, progressive worsening",
            "Migraine acute treatment: NSAIDs, triptans, or combination",
            "Consider preventive therapy if >=4 headache days/month",
        ],
        "lifestyle_modifications": [
            "Regular sleep schedule (7-8 hours)",
            "Adequate hydration",
            "Regular meals (avoid skipping)",
            "Stress management",
            "Headache diary to identify triggers",
        ],
        "monitoring": "Follow-up in 4-6 weeks if starting preventive therapy.",
        "red_flags_requiring_immediate_action": [
            "Thunderclap headache (worst headache of life, sudden onset)",
            "Fever with neck stiffness (meningitis concern)",
            "New neurologic deficits",
            "Headache after head trauma",
        ],
    },
    "depression": {
        "condition": "Major Depressive Disorder",
        "source": "APA Practice Guidelines 2023",
        "key_recommendations": [
            "Use PHQ-9 for initial screening and monitoring",
            "Mild: psychotherapy (CBT or IPT) as first-line",
            "Moderate-severe: combine antidepressant + psychotherapy",
            "First-line medications: SSRIs (sertraline, escitalopram) or SNRIs",
            "Assess for suicidal ideation at every visit using C-SSRS",
            "Minimum 6-9 months of treatment after remission",
        ],
        "lifestyle_modifications": [
            "Regular exercise (150 min/week moderate intensity)",
            "Sleep hygiene optimization",
            "Social engagement and support",
            "Reduced alcohol intake",
            "Mindfulness or meditation practice",
        ],
        "monitoring": "PHQ-9 every 2-4 weeks during acute treatment. Reassess at 4-6 weeks for medication response.",
        "red_flags_requiring_immediate_action": [
            "Active suicidal ideation with plan",
            "Psychotic features (hallucinations, delusions)",
            "Severe functional impairment (unable to care for self)",
        ],
    },
    "back_pain": {
        "condition": "Low Back Pain",
        "source": "ACP Clinical Practice Guideline",
        "key_recommendations": [
            "Most acute LBP is self-limiting (resolves in 4-6 weeks)",
            "First-line: NSAIDs, superficial heat, and continued activity",
            "Avoid routine imaging for acute LBP without red flags",
            "Red flags warranting imaging: cauda equina, cancer risk, fracture risk, infection",
            "Consider PT referral if not improving in 4 weeks",
        ],
        "lifestyle_modifications": [
            "Stay active — avoid prolonged bed rest",
            "Core strengthening exercises",
            "Proper lifting mechanics",
            "Ergonomic workspace assessment",
            "Weight management",
        ],
        "monitoring": "Reassess in 2-4 weeks if not improving. Image if red flags or no improvement at 6 weeks.",
        "red_flags_requiring_immediate_action": [
            "Bowel or bladder dysfunction (cauda equina syndrome)",
            "Progressive neurologic deficit",
            "Saddle anesthesia",
            "Fever with back pain (epidural abscess)",
        ],
    },
    "uti": {
        "condition": "Urinary Tract Infection",
        "source": "IDSA Guidelines",
        "key_recommendations": [
            "Uncomplicated cystitis: short-course antibiotics (nitrofurantoin 5 days or TMP-SMX 3 days)",
            "Avoid fluoroquinolones for uncomplicated UTI",
            "Urine culture recommended for recurrent UTIs or treatment failure",
            "Pyelonephritis: 7-14 day course, consider outpatient vs inpatient based on severity",
            "Recurrent UTIs (>=3/year): consider prophylactic strategies",
        ],
        "lifestyle_modifications": [
            "Adequate hydration",
            "Cranberry products may reduce recurrence (limited evidence)",
            "Post-coital voiding",
            "Avoid irritants (bubble baths, douches)",
        ],
        "monitoring": "No routine test-of-cure needed for uncomplicated UTI. Recheck if symptoms persist >48h on treatment.",
        "red_flags_requiring_immediate_action": [
            "High fever with flank pain (pyelonephritis)",
            "Inability to tolerate oral fluids/medications",
            "Sepsis signs (confusion, hypotension, tachycardia)",
        ],
    },
}

# Generic fallback
_GENERIC_GUIDELINE = {
    "condition": "General Assessment",
    "source": "Clinical Best Practice",
    "key_recommendations": [
        "Complete history and physical examination recommended",
        "Order appropriate diagnostic testing based on differential diagnosis",
        "Consider specialist referral if diagnosis uncertain or treatment refractory",
        "Document patient education and shared decision-making",
    ],
    "lifestyle_modifications": [
        "Regular exercise appropriate for condition",
        "Balanced nutrition",
        "Adequate sleep (7-9 hours)",
        "Stress management",
    ],
    "monitoring": "Follow-up as clinically indicated based on diagnosis and treatment plan.",
    "red_flags_requiring_immediate_action": [
        "Acute deterioration in condition",
        "New neurologic symptoms",
        "Signs of systemic infection (fever, chills, rigors)",
    ],
}


def check_guidelines(
    condition: str,
    patient_age: int | None = None,
    comorbidities: list[str] | None = None,
) -> dict:
    """Look up clinical practice guidelines for a condition."""
    comorbidities = comorbidities or []
    condition_key = condition.lower().replace(" ", "_").strip()

    # Try exact match first, then partial match
    guideline = _GUIDELINES.get(condition_key)
    if not guideline:
        for key, val in _GUIDELINES.items():
            if key in condition_key or condition_key in key:
                guideline = val
                break

    if not guideline:
        # Try matching on condition name in values
        for key, val in _GUIDELINES.items():
            if condition.lower() in val["condition"].lower():
                guideline = val
                break

    if not guideline:
        guideline = _GENERIC_GUIDELINE.copy()
        guideline["condition"] = condition
        guideline["note"] = f"No specific guideline found for '{condition}'. Showing general recommendations."

    result = dict(guideline)

    # Add age-specific notes
    if patient_age is not None:
        if patient_age >= 65:
            result["age_considerations"] = "Elderly patient — consider adjusted targets, fall risk, polypharmacy, and renal function."
        elif patient_age < 18:
            result["age_considerations"] = "Pediatric patient — adult guidelines may not apply. Consider pediatric-specific guidelines."

    if comorbidities:
        result["comorbidity_considerations"] = f"Patient has {', '.join(comorbidities)}. Treatment plan should account for these conditions."

    return result
