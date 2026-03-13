"""Patient profile generator — creates realistic, demographically diverse profiles.

Generates 1000+ unique patient profiles with realistic distributions for:
- Age, sex, demographics
- Conditions, symptoms, medications

from __future__ import annotations is used for Python 3.9 compat.
- Communication styles
- Edge cases (emergencies, pediatric, mental health)
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional
from models import (
    PatientProfile, Allergy, Vitals, LabValue,
    CommunicationStyle, AgentMode,
)

# ──────────────────────────────────────────────
# Weighted distributions to match real populations
# ──────────────────────────────────────────────

AGE_BRACKETS = [
    # (min, max, weight) — roughly US healthcare utilization
    (0, 2, 0.03),
    (3, 12, 0.05),
    (13, 17, 0.04),
    (18, 30, 0.15),
    (31, 45, 0.18),
    (46, 55, 0.15),
    (56, 65, 0.15),
    (66, 75, 0.13),
    (76, 90, 0.10),
    (91, 100, 0.02),
]

MODE_WEIGHTS = {
    AgentMode.TRIAGE: 0.40,
    AgentMode.INTAKE: 0.35,
    AgentMode.LAB_REVIEW: 0.25,
}

STYLE_WEIGHTS = {
    CommunicationStyle.MATTER_OF_FACT: 0.30,
    CommunicationStyle.ANXIOUS: 0.25,
    CommunicationStyle.VAGUE: 0.20,
    CommunicationStyle.MEDICAL_LITERATE: 0.15,
    CommunicationStyle.RAMBLING: 0.10,
}

# Common medications by category
MEDICATIONS = {
    "hypertension": [
        "lisinopril 10mg daily", "lisinopril 20mg daily",
        "amlodipine 5mg daily", "amlodipine 10mg daily",
        "losartan 50mg daily", "metoprolol 25mg twice daily",
        "hydrochlorothiazide 25mg daily",
    ],
    "diabetes": [
        "metformin 500mg twice daily", "metformin 1000mg twice daily",
        "glipizide 5mg daily", "sitagliptin 100mg daily",
    ],
    "cholesterol": [
        "atorvastatin 20mg daily", "atorvastatin 40mg daily",
        "rosuvastatin 10mg daily", "simvastatin 20mg daily",
    ],
    "depression_anxiety": [
        "sertraline 50mg daily", "sertraline 100mg daily",
        "fluoxetine 20mg daily", "escitalopram 10mg daily",
    ],
    "pain": [
        "ibuprofen 400mg as needed", "acetaminophen 500mg as needed",
        "naproxen 220mg twice daily", "gabapentin 300mg three times daily",
    ],
    "thyroid": [
        "levothyroxine 50mcg daily", "levothyroxine 75mcg daily",
        "levothyroxine 100mcg daily",
    ],
    "acid_reflux": [
        "omeprazole 20mg daily", "pantoprazole 40mg daily",
        "famotidine 20mg twice daily",
    ],
    "blood_thinners": [
        "warfarin 5mg daily", "apixaban 5mg twice daily",
        "clopidogrel 75mg daily",
    ],
    "asthma_copd": [
        "albuterol inhaler as needed", "fluticasone inhaler twice daily",
        "montelukast 10mg daily",
    ],
}

COMMON_ALLERGIES = [
    Allergy(allergen="penicillin", reaction="hives"),
    Allergy(allergen="sulfa drugs", reaction="rash"),
    Allergy(allergen="amoxicillin", reaction="swelling"),
    Allergy(allergen="aspirin", reaction="GI upset"),
    Allergy(allergen="codeine", reaction="nausea and vomiting"),
    Allergy(allergen="latex", reaction="skin irritation"),
    Allergy(allergen="iodine contrast", reaction="hives"),
    Allergy(allergen="shellfish", reaction="hives"),
    Allergy(allergen="peanuts", reaction="anaphylaxis"),
    Allergy(allergen="eggs", reaction="hives"),
]

# ──────────────────────────────────────────────
# Triage scenario templates
# ──────────────────────────────────────────────

TRIAGE_SCENARIOS = [
    # (chief_complaint, symptoms, red_flags, expected_urgency, edge_case_tags)
    # --- Common / Low urgency ---
    ("headache for 3 days", ["headache", "bilateral pressure", "mild pain", "neck tightness"], [], 5, ["common"]),
    ("sore throat and cough for a week", ["sore throat", "cough", "congestion", "mild fever"], [], 5, ["common"]),
    ("lower back pain after lifting", ["lower back pain", "muscle spasm", "stiffness"], [], 5, ["common"]),
    ("heartburn getting worse", ["heartburn", "acid regurgitation", "chest burning", "worse after meals"], [], 5, ["common"]),
    ("feeling tired all the time", ["fatigue", "low energy", "difficulty concentrating"], [], 5, ["common"]),
    ("runny nose and sneezing for 4 days", ["runny nose", "sneezing", "congestion", "post-nasal drip"], [], 5, ["common"]),
    ("knee pain worse with stairs", ["joint pain", "stiffness", "reduced range of motion", "crepitus"], [], 5, ["common"]),
    ("bloating and cramps after eating", ["abdominal cramping", "bloating", "alternating bowel habits"], [], 5, ["common"]),
    # --- Moderate urgency ---
    ("painful urination for 2 days", ["painful urination", "frequent urination", "urgency", "pelvic pain"], [], 3, ["common"]),
    ("migraine that won't go away", ["severe headache", "throbbing pain", "nausea", "light sensitivity"], [], 3, ["common"]),
    ("cough with yellow mucus for 10 days", ["persistent cough", "mucus production", "mild fever", "fatigue"], [], 4, ["common"]),
    ("ankle swelling and pain after a fall", ["swelling", "pain", "bruising", "difficulty walking"], [], 3, ["common"]),
    ("diarrhea and vomiting since last night", ["diarrhea", "vomiting", "abdominal cramps", "nausea"], [], 3, ["common"]),
    ("shooting pain down my leg", ["lower back pain radiating to leg", "shooting pain", "numbness", "tingling"], [], 3, ["common"]),
    ("really bad period cramps", ["severe pelvic pain", "cramping", "nausea", "heavy bleeding"], [], 3, ["common"]),
    ("itchy red rash spreading on arm", ["skin redness", "warmth", "swelling", "spreading redness"], [], 3, ["common"]),
    # --- Urgent ---
    ("sharp pain in my right side", ["right lower abdominal pain", "nausea", "loss of appetite", "low-grade fever"], [], 2, ["surgical"]),
    ("severe flank pain and blood in urine", ["severe flank pain", "colicky pain", "blood in urine", "nausea"], [], 2, ["common"]),
    ("heart racing and feeling dizzy", ["palpitations", "dizziness", "irregular heartbeat", "shortness of breath"], ["chest pain", "syncope"], 2, ["cardiac"]),
    ("painful blistering rash on my side", ["painful rash", "blistering rash", "burning pain", "one-sided"], [], 3, ["common"]),
    ("high fever and flank pain", ["flank pain", "high fever", "chills", "painful urination"], [], 2, ["infection"]),
    # --- Emergency ---
    ("crushing chest pain and sweating", ["severe chest pain", "crushing chest pressure", "diaphoresis", "pain radiating to left arm", "nausea"], ["crushing chest pressure", "diaphoresis"], 1, ["cardiac", "emergency"]),
    ("my face is drooping and arm is weak", ["facial drooping", "arm weakness", "speech difficulty", "sudden onset"], ["facial drooping", "arm weakness", "speech difficulty"], 1, ["neuro", "emergency"]),
    ("worst headache of my life, came on suddenly", ["worst headache of life", "sudden onset", "severe headache", "nausea", "stiff neck"], ["worst headache of life", "sudden onset"], 1, ["neuro", "emergency"]),
    ("throat closing up after eating shrimp", ["throat tightness", "difficulty breathing", "widespread hives", "rapid heartbeat", "swelling"], ["throat tightness", "difficulty breathing"], 1, ["allergy", "emergency"]),
    ("I'm having a seizure-like episode right now", ["seizure", "convulsion", "altered consciousness"], ["seizure"], 1, ["neuro", "emergency"]),
    # --- Mental health ---
    ("feeling really down for months, can't get out of bed", ["persistent sadness", "loss of interest", "fatigue", "sleep changes", "feelings of worthlessness"], [], 3, ["mental_health"]),
    ("constant anxiety and panic attacks", ["excessive worry", "heart racing", "sudden intense fear", "trembling", "difficulty breathing"], [], 3, ["mental_health"]),
    ("I've been having thoughts about ending my life", ["suicidal ideation with plan", "persistent sadness", "hopelessness", "loss of interest"], ["suicidal ideation with plan"], 1, ["mental_health", "emergency"]),
    # --- Pediatric edge cases ---
    ("my 2-month-old has a fever", ["fever in infant", "fussiness", "poor feeding"], ["fever in infant under 3 months"], 1, ["pediatric", "neonatal", "emergency"]),
    ("my 5-year-old has been vomiting all day", ["vomiting", "fever", "abdominal pain", "lethargy"], ["signs of dehydration"], 2, ["pediatric"]),
    # --- Complex / polypharmacy ---
    ("I feel dizzy and my heart is racing", ["dizziness", "palpitations", "fatigue", "lightheadedness"], [], 2, ["cardiac", "polypharmacy"]),
]

# ──────────────────────────────────────────────
# Intake scenario templates
# ──────────────────────────────────────────────

INTAKE_SCENARIOS = [
    # (chief_complaint, visit_reason)
    ("annual physical exam", "routine checkup, no new complaints"),
    ("follow-up for blood pressure management", "checking on hypertension control"),
    ("follow-up for diabetes management", "A1C check and medication review"),
    ("new patient visit — transferring care", "establishing care with new provider"),
    ("pre-surgical clearance", "preparing for upcoming knee replacement"),
    ("follow-up after ER visit for chest pain", "checking in after ER discharge 3 days ago"),
    ("wellness visit and preventive care", "overdue for screenings"),
    ("medication refill and check-in", "need to renew prescriptions"),
    ("follow-up for depression treatment", "started medication 6 weeks ago"),
    ("pregnancy confirmation visit", "missed period and positive home test"),
    ("post-hospitalization follow-up", "discharged from hospital last week for pneumonia"),
    ("chronic pain management follow-up", "ongoing lower back pain management"),
]

# ──────────────────────────────────────────────
# Lab review scenario templates
# ──────────────────────────────────────────────

def _jitter(base: float, pct: float = 0.15) -> float:
    """Add random jitter to a lab value. Keeps clinical meaning intact."""
    return round(base * random.uniform(1 - pct, 1 + pct), 1)


def _make_lab_scenario(template: tuple) -> tuple:
    """Create a lab scenario with randomized values from a template."""
    desc, lab_specs, patterns, tags = template
    labs = [LabValue(test=t, value=_jitter(v), unit=u) for t, v, u in lab_specs]
    return (desc, labs, patterns, tags)


# Lab templates: (test, base_value, unit) — values get jittered at generation time
_LAB_TEMPLATES = [
    ("routine CBC - all normal", [
        ("WBC", 7.2, "K/uL"), ("Hemoglobin", 14.1, "g/dL"),
        ("Hematocrit", 42.0, "%"), ("MCV", 88.0, "fL"), ("Platelets", 250.0, "K/uL"),
    ], [], ["normal"]),
    ("iron deficiency anemia pattern", [
        ("WBC", 6.8, "K/uL"), ("Hemoglobin", 9.8, "g/dL"),
        ("Hematocrit", 30.0, "%"), ("MCV", 72.0, "fL"), ("Platelets", 320.0, "K/uL"),
    ], ["Iron Deficiency Anemia"], ["abnormal"]),
    ("elevated liver enzymes", [
        ("ALT", 125.0, "U/L"), ("AST", 98.0, "U/L"),
        ("ALP", 90.0, "U/L"), ("Bilirubin", 1.0, "mg/dL"), ("Albumin", 3.8, "g/dL"),
    ], ["Hepatocellular Injury"], ["abnormal"]),
    ("kidney function decline", [
        ("BUN", 35.0, "mg/dL"), ("Creatinine", 2.1, "mg/dL"),
        ("Potassium", 5.3, "mEq/L"), ("Sodium", 138.0, "mEq/L"), ("Glucose", 95.0, "mg/dL"),
    ], ["Kidney Dysfunction"], ["abnormal"]),
    ("poorly controlled diabetes", [
        ("HbA1c", 9.8, "%"), ("Glucose", 245.0, "mg/dL"),
    ], ["Poorly Controlled Diabetes", "Diabetes Risk"], ["abnormal", "critical"]),
    ("hypothyroid pattern", [
        ("TSH", 12.5, "mIU/L"), ("Free T4", 0.6, "ng/dL"),
    ], ["Primary Hypothyroidism"], ["abnormal"]),
    ("hyperthyroid pattern", [
        ("TSH", 0.05, "mIU/L"), ("Free T4", 3.2, "ng/dL"), ("Free T3", 6.8, "pg/mL"),
    ], ["Hyperthyroidism"], ["abnormal"]),
    ("high cardiovascular risk lipids", [
        ("Total Cholesterol", 280.0, "mg/dL"), ("LDL", 185.0, "mg/dL"),
        ("HDL", 32.0, "mg/dL"), ("Triglycerides", 310.0, "mg/dL"),
    ], ["High Cardiovascular Risk"], ["abnormal"]),
    ("normal lipid panel", [
        ("Total Cholesterol", 185.0, "mg/dL"), ("LDL", 95.0, "mg/dL"),
        ("HDL", 62.0, "mg/dL"), ("Triglycerides", 110.0, "mg/dL"),
    ], [], ["normal"]),
    ("critically low hemoglobin", [
        ("WBC", 5.5, "K/uL"), ("Hemoglobin", 6.2, "g/dL"),
        ("Hematocrit", 19.0, "%"), ("Platelets", 180.0, "K/uL"),
    ], [], ["critical"]),
    ("UTI on urinalysis", [
        ("WBC", 25.0, "/HPF"), ("Bacteria", 1.0, ""), ("pH", 7.5, ""),
    ], ["Urinary Tract Infection"], ["abnormal"]),
    ("well controlled diabetes", [
        ("HbA1c", 6.4, "%"), ("Glucose", 105.0, "mg/dL"),
    ], [], ["normal"]),
    ("critical potassium", [
        ("Potassium", 6.8, "mEq/L"), ("Sodium", 140.0, "mEq/L"),
        ("BUN", 28.0, "mg/dL"), ("Creatinine", 1.8, "mg/dL"),
    ], ["Kidney Dysfunction", "Electrolyte Imbalance"], ["critical"]),
]

# ──────────────────────────────────────────────
# Triage modifiers — randomize each scenario
# ──────────────────────────────────────────────

DURATION_VARIANTS = [
    "since this morning", "since yesterday", "for about 2 days", "for 3 days now",
    "for almost a week", "for about a week", "on and off for 10 days",
    "for the past 2 weeks", "for about a month", "a few hours ago",
    "started last night", "since Tuesday", "going on 4 days",
]

SEVERITY_MODIFIERS = [
    ("mild", ["It's not terrible but", "It's manageable but", "It's a dull"]),
    ("moderate", ["It's pretty bad", "It's been getting worse", "It's hard to ignore"]),
    ("severe", ["It's the worst I've ever felt", "I can barely function", "It's excruciating"]),
]

SELF_CARE_ATTEMPTS = [
    "Took some Advil", "Tried Tylenol", "Used ibuprofen", "Rested for a day",
    "Applied ice", "Used a heating pad", "Drank lots of water", "Took Pepto-Bismol",
    "Tried Benadryl", "Used Tums", "Skipped meals", "Took my spouse's leftover antibiotics",
    "Tried CBD oil", "Used a hot compress", "Tried melatonin for sleep", "Took Excedrin",
    "Got some Sudafed", "Used Vicks VapoRub", "Tried ginger tea", "Nothing yet",
]

TANGENTIAL_DETAILS = [
    "My neighbor had something like this last year.",
    "My coworker said I should get it checked.",
    "I Googled it and now I'm worried.",
    "My sister thinks it's nothing.",
    "I've been stressed at work lately, so maybe it's that?",
    "I haven't been sleeping well either.",
    "I was fine until I ate at that new restaurant.",
    "It reminds me of what my mother had.",
    "I tried to ignore it but my wife made me call.",
    "The weather's been changing a lot, maybe that's it?",
    "I missed work yesterday because of it.",
    "I almost went to the ER last night.",
]

ANXIOUS_WORRIES = [
    "Could this be cancer?", "Is this a heart attack?", "Am I having a stroke?",
    "Should I go to the ER?", "My dad died from something like this.",
    "I read online it could be really serious.", "I'm scared this won't go away.",
    "What if it's something really bad?", "I can't stop thinking about it.",
    "My doctor said to watch it but I'm panicking.",
]


def _randomize_complaint(base_complaint: str) -> str:
    """Add random duration/context to a chief complaint."""
    duration = random.choice(DURATION_VARIANTS)
    return f"{base_complaint} {duration}"



def _weighted_choice(options_weights: dict):
    """Pick from a dict of {option: weight}."""
    options = list(options_weights.keys())
    weights = list(options_weights.values())
    return random.choices(options, weights=weights, k=1)[0]


def _random_age() -> int:
    """Generate age following healthcare utilization distribution."""
    bracket = random.choices(AGE_BRACKETS, weights=[b[2] for b in AGE_BRACKETS], k=1)[0]
    return random.randint(bracket[0], bracket[1])


def _assign_chronic_conditions(age: int) -> list[str]:
    """Assign chronic conditions based on age-related prevalence."""
    conditions = []
    if age >= 40 and random.random() < 0.25:
        conditions.append("hypertension")
    if age >= 45 and random.random() < 0.12:
        conditions.append("type 2 diabetes")
    if age >= 40 and random.random() < 0.15:
        conditions.append("hyperlipidemia")
    if age >= 20 and random.random() < 0.10:
        conditions.append("depression")
    if age >= 20 and random.random() < 0.08:
        conditions.append("anxiety disorder")
    if age >= 50 and random.random() < 0.10:
        conditions.append("hypothyroidism")
    if age >= 10 and random.random() < 0.08:
        conditions.append("asthma")
    if age >= 30 and random.random() < 0.10:
        conditions.append("GERD")
    if age >= 60 and random.random() < 0.10:
        conditions.append("osteoarthritis")
    if age >= 50 and random.random() < 0.05:
        conditions.append("atrial fibrillation")
    return conditions


def _assign_medications(conditions: list[str], age: int) -> list[str]:
    """Assign realistic medications based on conditions."""
    meds = []
    cond_to_med_category = {
        "hypertension": "hypertension",
        "type 2 diabetes": "diabetes",
        "hyperlipidemia": "cholesterol",
        "depression": "depression_anxiety",
        "anxiety disorder": "depression_anxiety",
        "hypothyroidism": "thyroid",
        "GERD": "acid_reflux",
        "atrial fibrillation": "blood_thinners",
        "asthma": "asthma_copd",
    }
    for cond in conditions:
        cat = cond_to_med_category.get(cond)
        if cat and cat in MEDICATIONS:
            meds.append(random.choice(MEDICATIONS[cat]))

    # Common OTC and supplement use — most adults take something
    if age >= 18 and random.random() < 0.50:
        meds.append(random.choice(MEDICATIONS["pain"]))
    if age >= 30 and random.random() < 0.35:
        meds.append(random.choice([
            "vitamin D 2000 IU daily", "fish oil 1000mg daily",
            "multivitamin daily", "calcium 600mg daily",
            "magnesium 400mg daily", "vitamin B12 1000mcg daily",
            "melatonin 3mg at bedtime", "probiotic daily",
        ]))
    if age >= 40 and random.random() < 0.20:
        meds.append("aspirin 81mg daily")

    return meds


def _assign_allergies() -> list[Allergy]:
    """Assign allergies — ~20% of people have at least one."""
    if random.random() > 0.20:
        return []
    count = random.choices([1, 2, 3], weights=[0.7, 0.2, 0.1], k=1)[0]
    return random.sample(COMMON_ALLERGIES, min(count, len(COMMON_ALLERGIES)))


def _assign_family_history(age: int) -> list[str]:
    """Assign family history."""
    history = []
    if random.random() < 0.15:
        history.append(f"Father: heart attack at age {random.randint(48, 72)}")
    if random.random() < 0.10:
        history.append("Mother: breast cancer")
    if random.random() < 0.12:
        history.append("Mother: type 2 diabetes")
    if random.random() < 0.08:
        history.append("Father: colon cancer")
    if random.random() < 0.10:
        history.append("Parent: hypertension")
    if random.random() < 0.06:
        history.append("Sibling: depression")
    return history


def _assign_social_history(age: int) -> dict:
    """Assign social history."""
    social = {}
    if age >= 18:
        tobacco = random.choices(
            ["never", "former smoker, quit {n} years ago", "current, {n} cigarettes/day"],
            weights=[0.65, 0.20, 0.15], k=1
        )[0]
        if "{n}" in tobacco:
            tobacco = tobacco.replace("{n}", str(random.randint(1, 20)))
        social["tobacco"] = tobacco

        alcohol = random.choices(
            ["none", "social, 1-2 drinks/week", "moderate, 3-7 drinks/week", "heavy, >14 drinks/week"],
            weights=[0.30, 0.40, 0.20, 0.10], k=1
        )[0]
        social["alcohol"] = alcohol

        if random.random() < 0.05:
            social["other"] = random.choice(["marijuana occasionally", "history of opioid use, in recovery"])
    return social


def _generate_vitals(age: int, conditions: list[str]) -> Vitals | None:
    """Generate vitals — ~40% of patients have home monitoring."""
    if random.random() > 0.40:
        return None

    systolic = random.randint(110, 135)
    diastolic = random.randint(70, 85)
    if "hypertension" in conditions:
        systolic = random.randint(130, 165)
        diastolic = random.randint(80, 100)

    hr = random.randint(60, 90)
    if "atrial fibrillation" in conditions:
        hr = random.randint(80, 130)

    return Vitals(
        bp=f"{systolic}/{diastolic}",
        hr=hr,
        temp=round(random.uniform(97.5, 99.0), 1),
    )


def _build_opening_message(
    mode: AgentMode,
    style: CommunicationStyle,
    complaint: str,
    medications: list[str],
    history: list[str],
    family_history: list[str],
    labs: list[LabValue] | None,
) -> str:
    """Build a stochastic opening message assembled from random fragments.

    Each call produces a unique message even for the same scenario/style combo.
    """
    # Greetings vary by style
    greetings = {
        CommunicationStyle.MEDICAL_LITERATE: random.choice([
            "Hello", "Hi there", "Good morning", "Hi",
        ]),
        CommunicationStyle.VAGUE: random.choice([
            "Hey, um", "Hi, so", "Yeah so", "Hey",
        ]),
        CommunicationStyle.ANXIOUS: random.choice([
            "Hi, I'm really worried", "Please help me", "I'm scared",
            "I need help, I'm freaking out a little",
        ]),
        CommunicationStyle.MATTER_OF_FACT: "",  # No greeting, straight to point
        CommunicationStyle.RAMBLING: random.choice([
            "Oh hi there", "Hello! So", "Hi, sorry to bother you",
            "Oh good, someone's here",
        ]),
    }

    greeting = greetings.get(style, "Hi")
    duration = random.choice(DURATION_VARIANTS)
    self_care = random.choice(SELF_CARE_ATTEMPTS)
    severity = random.choice(SEVERITY_MODIFIERS)

    if mode == AgentMode.TRIAGE:
        # Core complaint with random duration
        core = f"I've been having {complaint} {duration}."

        if style == CommunicationStyle.MATTER_OF_FACT:
            return f"{complaint.capitalize()}. {duration.capitalize()}. {self_care}. Didn't help much."

        elif style == CommunicationStyle.VAGUE:
            vague_add = random.choice([
                "I'm not sure how to describe it.",
                "It's kind of hard to explain.",
                "I don't know, it's just weird.",
                "It comes and goes, I think?",
            ])
            return f"{greeting}, {core} {vague_add}"

        elif style == CommunicationStyle.ANXIOUS:
            worry = random.choice(ANXIOUS_WORRIES)
            return f"{greeting}. {core} {severity[1][0]} and I'm really nervous. {worry}"

        elif style == CommunicationStyle.RAMBLING:
            tangent = random.choice(TANGENTIAL_DETAILS)
            return f"{greeting}. So, {core} {tangent} Anyway, {severity[1][0].lower()} and I figured I should check. {self_care} but I'm not sure it did anything."

        elif style == CommunicationStyle.MEDICAL_LITERATE:
            med_note = f"I'm currently taking {medications[0]}" if medications else "No current medications"
            hist_note = f"with a history of {history[0]}" if history else ""
            return f"{greeting}. {core} {severity[1][0]}. {med_note} {hist_note}. Can you help me assess the situation?"

        return f"{greeting}. {core}"

    elif mode == AgentMode.INTAKE:
        visit_reasons = {
            CommunicationStyle.MATTER_OF_FACT: f"Here for {complaint}. What do you need?",
            CommunicationStyle.VAGUE: f"{greeting}, I think I'm here for {complaint}? My doctor's office told me to come in.",
            CommunicationStyle.ANXIOUS: f"{greeting}. I'm here for {complaint}. I hope everything checks out okay — I've been a little anxious about it.",
            CommunicationStyle.RAMBLING: f"{greeting}. So they called me and said it was time for {complaint}, and I've been meaning to come in for a while anyway. There's been a couple things on my mind, nothing major probably.",
            CommunicationStyle.MEDICAL_LITERATE: f"{greeting}. I'm here for {complaint}. I have a history of {history[0] if history else 'nothing major'} and I'm on {medications[0].split()[0] if medications else 'no medications'}. Happy to provide whatever you need.",
        }
        return visit_reasons.get(style, f"Hi, I'm here for {complaint}.")

    elif mode == AgentMode.LAB_REVIEW:
        if not labs:
            return "I got some lab results back and need help understanding them."

        first_lab = labs[0]
        lab_list_str = ", ".join(f"{l.test}: {l.value}" for l in labs[:3])

        lab_openers = {
            CommunicationStyle.MATTER_OF_FACT: f"Got my labs back. {lab_list_str}. What does this mean?",
            CommunicationStyle.VAGUE: f"{greeting}, I got some test results and I have no idea what any of it means. There were a bunch of numbers.",
            CommunicationStyle.ANXIOUS: f"{greeting}. My doctor sent my lab results and some numbers are flagged. {random.choice(ANXIOUS_WORRIES)} My {first_lab.test} was {first_lab.value}.",
            CommunicationStyle.RAMBLING: f"{greeting}. So I got these results through the patient portal, and I tried looking things up but that just scared me more. {random.choice(TANGENTIAL_DETAILS)} Anyway, can you help me understand what {first_lab.test} at {first_lab.value} means?",
            CommunicationStyle.MEDICAL_LITERATE: f"{greeting}. I received my lab panel — {lab_list_str}. I notice my {first_lab.test} looks {'elevated' if first_lab.value > 100 else 'off'}. Can you walk me through the full picture?",
        }
        return lab_openers.get(style, f"I got my lab results. {lab_list_str}.")


def generate_profiles(count: int = 1050, seed: int = -1) -> list[PatientProfile]:
    """Generate `count` unique patient profiles. seed=-1 means random each time."""
    if seed >= 0:
        random.seed(seed)
    # else: no seed, fully stochastic
    profiles = []

    for i in range(count):
        age = _random_age()
        sex = random.choice(["male", "female"])
        mode = _weighted_choice(MODE_WEIGHTS)
        style = _weighted_choice(STYLE_WEIGHTS)
        chronic = _assign_chronic_conditions(age)
        medications = _assign_medications(chronic, age)
        allergies = _assign_allergies()
        family_history = _assign_family_history(age)
        social = _assign_social_history(age)
        vitals = _generate_vitals(age, chronic)

        labs = None
        edge_tags = []
        red_flags = []
        expected_urgency = None

        if mode == AgentMode.TRIAGE:
            scenario = random.choice(TRIAGE_SCENARIOS)
            chief_complaint = scenario[0]
            extra_symptoms = scenario[1]
            red_flags = scenario[2]
            expected_urgency = scenario[3]
            edge_tags = scenario[4]

            # Override vitals for emergency scenarios
            if expected_urgency == 1 and "cardiac" in edge_tags:
                vitals = Vitals(bp="90/60", hr=120, temp=98.6, spo2=92)

        elif mode == AgentMode.INTAKE:
            scenario = random.choice(INTAKE_SCENARIOS)
            chief_complaint = scenario[0]
            edge_tags = ["intake"]

        elif mode == AgentMode.LAB_REVIEW:
            template = random.choice(_LAB_TEMPLATES)
            scenario = _make_lab_scenario(template)
            chief_complaint = f"lab results - {scenario[0]}"
            labs = scenario[1]
            edge_tags = scenario[3]

        opening = _build_opening_message(
            mode, style, chief_complaint,
            medications, chronic, family_history, labs,
        )

        profile = PatientProfile(
            id=f"patient_{i:04d}",
            age=age,
            sex=sex,
            mode=mode,
            chief_complaint=chief_complaint,
            communication_style=style,
            medications=medications,
            allergies=allergies,
            medical_history=chronic,
            family_history=family_history,
            social=social,
            vitals=vitals,
            labs=labs,
            opening_message=opening,
            expected_urgency=expected_urgency,
            red_flags_present=red_flags,
            edge_case_tags=edge_tags,
        )
        profiles.append(profile)

    return profiles


def save_profiles(profiles: list[PatientProfile], path: str | Path):
    """Save profiles to JSON."""
    path = Path(path)
    data = [p.model_dump(mode="json") for p in profiles]
    path.write_text(json.dumps(data, indent=2, default=str))


def load_profiles(path: str | Path) -> list[PatientProfile]:
    """Load profiles from JSON."""
    path = Path(path)
    data = json.loads(path.read_text())
    return [PatientProfile.model_validate(d) for d in data]


if __name__ == "__main__":
    profiles = generate_profiles(1050)
    out = Path(__file__).parent / "patient_profiles.json"
    save_profiles(profiles, out)
    print(f"Generated {len(profiles)} profiles -> {out}")

    # Print distribution stats
    from collections import Counter
    modes = Counter(p.mode.value for p in profiles)
    styles = Counter(p.communication_style.value for p in profiles)
    urgencies = Counter(p.expected_urgency for p in profiles if p.expected_urgency is not None)
    ages = Counter("0-17" if p.age < 18 else "18-45" if p.age < 46 else "46-65" if p.age < 66 else "66+" for p in profiles)

    print(f"\nMode distribution: {dict(modes)}")
    print(f"Style distribution: {dict(styles)}")
    print(f"Urgency distribution: {dict(urgencies)}")
    print(f"Age distribution: {dict(ages)}")
    print(f"Avg medications: {sum(len(p.medications) for p in profiles) / len(profiles):.1f}")
    print(f"With allergies: {sum(1 for p in profiles if p.allergies)}")
    print(f"Emergency cases: {sum(1 for p in profiles if p.expected_urgency == 1)}")
