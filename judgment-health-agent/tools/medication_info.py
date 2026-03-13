"""Medication information lookup — returns details about medications."""

from __future__ import annotations


_MEDICATION_DB = {
    "lisinopril": {
        "name": "Lisinopril",
        "class": "ACE Inhibitor",
        "primary_use": "Hypertension, heart failure, post-MI",
        "common_doses": "5-40mg daily",
        "common_side_effects": ["dry cough", "dizziness", "headache", "hyperkalemia"],
        "serious_side_effects": ["angioedema", "renal impairment", "severe hyperkalemia"],
        "contraindications": ["pregnancy", "bilateral renal artery stenosis", "history of angioedema with ACEi"],
        "monitoring": ["Renal function (BUN/Cr)", "Potassium levels", "Blood pressure"],
        "food_interactions": "Avoid potassium-rich salt substitutes. Take consistently with or without food.",
        "notes": "Dry cough occurs in ~10-15% of patients. If intolerable, consider switching to ARB.",
    },
    "metformin": {
        "name": "Metformin",
        "class": "Biguanide",
        "primary_use": "Type 2 diabetes, insulin resistance, PCOS",
        "common_doses": "500-2000mg daily (divided doses)",
        "common_side_effects": ["GI upset", "diarrhea", "nausea", "metallic taste"],
        "serious_side_effects": ["lactic acidosis (rare)", "vitamin B12 deficiency"],
        "contraindications": ["eGFR <30", "acute/chronic metabolic acidosis", "use of iodinated contrast (hold 48h)"],
        "monitoring": ["Renal function (at least annually)", "Vitamin B12 levels (periodically)", "A1C every 3-6 months"],
        "food_interactions": "Take with meals to reduce GI side effects. Extended-release should be taken with evening meal.",
        "notes": "Most common first-line diabetes medication. GI side effects often improve over 2-4 weeks.",
    },
    "atorvastatin": {
        "name": "Atorvastatin",
        "class": "HMG-CoA Reductase Inhibitor (Statin)",
        "primary_use": "Hyperlipidemia, cardiovascular risk reduction",
        "common_doses": "10-80mg daily",
        "common_side_effects": ["myalgia", "headache", "GI upset", "elevated liver enzymes"],
        "serious_side_effects": ["rhabdomyolysis", "hepatotoxicity", "new-onset diabetes"],
        "contraindications": ["active liver disease", "pregnancy", "breastfeeding"],
        "monitoring": ["Lipid panel (4-12 weeks after starting, then annually)", "Liver enzymes (baseline, as needed)", "CK if muscle symptoms"],
        "food_interactions": "Avoid large quantities of grapefruit juice. Can be taken with or without food.",
        "notes": "Muscle pain reported by ~5-10% of patients. If CK elevated >10x ULN, discontinue.",
    },
    "sertraline": {
        "name": "Sertraline",
        "class": "SSRI (Selective Serotonin Reuptake Inhibitor)",
        "primary_use": "Depression, anxiety disorders, PTSD, OCD, panic disorder",
        "common_doses": "50-200mg daily",
        "common_side_effects": ["nausea", "diarrhea", "insomnia", "sexual dysfunction", "drowsiness"],
        "serious_side_effects": ["serotonin syndrome", "suicidal ideation (especially age <25)", "hyponatremia", "bleeding risk"],
        "contraindications": ["concurrent MAOIs (14-day washout)", "concurrent pimozide"],
        "monitoring": ["Depression screening (PHQ-9) at follow-ups", "Suicidal ideation assessment", "Sodium levels if elderly"],
        "food_interactions": "Can be taken with or without food. Avoid alcohol.",
        "notes": "Full therapeutic effect may take 4-6 weeks. Do not abruptly discontinue — taper gradually.",
    },
    "omeprazole": {
        "name": "Omeprazole",
        "class": "Proton Pump Inhibitor (PPI)",
        "primary_use": "GERD, peptic ulcer, H. pylori (combination), Zollinger-Ellison",
        "common_doses": "20-40mg daily",
        "common_side_effects": ["headache", "nausea", "diarrhea", "abdominal pain", "flatulence"],
        "serious_side_effects": ["C. difficile infection", "bone fractures (long-term)", "hypomagnesemia", "vitamin B12 deficiency"],
        "contraindications": ["Known hypersensitivity"],
        "monitoring": ["Magnesium levels (if long-term use)", "Consider bone density (if >1 year use)", "Reassess need periodically"],
        "food_interactions": "Take 30-60 minutes before first meal of the day for best efficacy.",
        "notes": "Avoid long-term use if possible. Reassess need every 6-12 months. Consider step-down to H2 blocker.",
    },
    "ibuprofen": {
        "name": "Ibuprofen",
        "class": "NSAID (Non-Steroidal Anti-Inflammatory Drug)",
        "primary_use": "Pain, inflammation, fever, arthritis",
        "common_doses": "200-800mg every 4-8 hours (max 3200mg/day)",
        "common_side_effects": ["GI upset", "nausea", "heartburn", "dizziness"],
        "serious_side_effects": ["GI bleeding", "renal impairment", "cardiovascular events (long-term)", "hypertension worsening"],
        "contraindications": ["Active GI bleeding", "severe renal impairment", "third trimester pregnancy", "post-CABG surgery"],
        "monitoring": ["Renal function (if chronic use)", "Blood pressure", "Signs of GI bleeding"],
        "food_interactions": "Take with food or milk to reduce GI irritation.",
        "notes": "Use lowest effective dose for shortest duration. Avoid combining with other NSAIDs or anticoagulants.",
    },
    "levothyroxine": {
        "name": "Levothyroxine",
        "class": "Thyroid Hormone Replacement",
        "primary_use": "Hypothyroidism, thyroid cancer (TSH suppression)",
        "common_doses": "25-200mcg daily",
        "common_side_effects": ["dose-dependent: palpitations, tremor, insomnia, weight loss (if over-replaced)"],
        "serious_side_effects": ["atrial fibrillation (over-replacement)", "osteoporosis (chronic over-replacement)", "angina"],
        "contraindications": ["Uncorrected adrenal insufficiency", "Acute MI (relative)"],
        "monitoring": ["TSH every 6-8 weeks after dose change", "Annual TSH once stable", "Free T4 if TSH discordant"],
        "food_interactions": "Take on empty stomach, 30-60 min before breakfast. Separate from calcium, iron, and antacids by 4 hours.",
        "notes": "Consistent timing and brand important. Many drug and food interactions affect absorption.",
    },
    "amlodipine": {
        "name": "Amlodipine",
        "class": "Calcium Channel Blocker (Dihydropyridine)",
        "primary_use": "Hypertension, angina, coronary artery disease",
        "common_doses": "2.5-10mg daily",
        "common_side_effects": ["peripheral edema", "dizziness", "flushing", "headache"],
        "serious_side_effects": ["severe hypotension", "reflex tachycardia", "worsening heart failure (rare)"],
        "contraindications": ["Severe aortic stenosis", "Cardiogenic shock"],
        "monitoring": ["Blood pressure", "Heart rate", "Lower extremity edema"],
        "food_interactions": "Can be taken with or without food. Avoid grapefruit juice (increases levels).",
        "notes": "Long-acting — once daily dosing. Ankle edema is most common reason for discontinuation.",
    },
    "aspirin": {
        "name": "Aspirin (Low-Dose)",
        "class": "Antiplatelet / NSAID",
        "primary_use": "Cardiovascular prevention, post-MI, post-stroke",
        "common_doses": "81mg daily (low-dose), 325mg (acute events)",
        "common_side_effects": ["GI upset", "easy bruising", "heartburn"],
        "serious_side_effects": ["GI bleeding", "hemorrhagic stroke", "aspirin-exacerbated respiratory disease"],
        "contraindications": ["Active bleeding", "Aspirin allergy/sensitivity", "Children with viral illness (Reye syndrome)"],
        "monitoring": ["Signs of bleeding", "GI symptoms", "Platelet function if surgical planning"],
        "food_interactions": "Take with food to reduce GI irritation. Avoid concurrent high-dose NSAIDs.",
        "notes": "USPSTF 2022: Do not initiate for primary prevention in adults >60. Individualize for ages 40-59.",
    },
}


def _normalize_med_name(name: str) -> str:
    """Extract drug name from a string like 'lisinopril 10mg daily'."""
    return name.lower().split()[0].strip()


def lookup_medication_info(medication_name: str) -> dict:
    """Look up detailed information about a medication."""
    key = _normalize_med_name(medication_name)

    info = _MEDICATION_DB.get(key)
    if info:
        return {
            "found": True,
            "medication": info,
        }

    # Try partial match
    for db_key, db_val in _MEDICATION_DB.items():
        if db_key in key or key in db_key:
            return {
                "found": True,
                "medication": db_val,
                "note": f"Matched '{medication_name}' to {db_val['name']}",
            }

    return {
        "found": False,
        "medication_name": medication_name,
        "note": f"No detailed information found for '{medication_name}'. Recommend consulting a pharmacist or prescriber.",
        "general_advice": "Always take medications as prescribed. Report any new side effects to your healthcare provider.",
    }
