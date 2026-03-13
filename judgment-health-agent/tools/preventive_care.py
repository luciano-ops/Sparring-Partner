"""Preventive care checker — identifies due screenings and vaccines by age/sex."""

from __future__ import annotations


def check_preventive_care(
    patient_age: int,
    patient_sex: str,
    medical_history: list[str] | None = None,
    last_screenings: dict | None = None,
) -> dict:
    """Check which preventive care screenings are recommended for this patient."""
    medical_history = medical_history or []
    last_screenings = last_screenings or {}
    sex = patient_sex.lower()
    recommendations = []
    overdue = []

    # Cancer screenings
    if patient_age >= 45 and patient_age <= 75:
        rec = {
            "screening": "Colorectal cancer screening",
            "guideline": "USPSTF Grade A (45-75)",
            "frequency": "Every 10 years (colonoscopy) or every 1-3 years (stool-based)",
            "notes": "Earlier if family history of colorectal cancer or polyps",
        }
        recommendations.append(rec)
        if "colorectal" not in str(last_screenings).lower():
            overdue.append("Colorectal cancer screening — no record of recent screening")

    if sex == "female" and patient_age >= 21 and patient_age <= 65:
        rec = {
            "screening": "Cervical cancer screening",
            "guideline": "USPSTF Grade A",
            "frequency": "Pap every 3 years (21-29) or Pap+HPV co-test every 5 years (30-65)",
            "notes": "May discontinue after 65 if adequate prior screening and not high risk",
        }
        recommendations.append(rec)

    if sex == "female" and patient_age >= 50:
        rec = {
            "screening": "Breast cancer screening (mammography)",
            "guideline": "USPSTF Grade B (40-74)",
            "frequency": "Every 2 years",
            "notes": "Discuss with provider if family history — may start earlier",
        }
        recommendations.append(rec)
        if "mammogram" not in str(last_screenings).lower():
            overdue.append("Mammography — recommended every 2 years")

    if sex == "male" and patient_age >= 55 and patient_age <= 69:
        rec = {
            "screening": "Prostate cancer screening discussion",
            "guideline": "USPSTF Grade C (individual decision)",
            "frequency": "Shared decision-making with provider",
            "notes": "PSA screening — discuss benefits and harms with provider",
        }
        recommendations.append(rec)

    if patient_age >= 50 and any("smoking" in h.lower() or "smoker" in h.lower() or "tobacco" in h.lower() for h in medical_history):
        rec = {
            "screening": "Lung cancer screening (low-dose CT)",
            "guideline": "USPSTF Grade B (50-80 with 20+ pack-year history)",
            "frequency": "Annually",
            "notes": "For adults 50-80 with 20+ pack-year smoking history (current or quit within 15 years)",
        }
        recommendations.append(rec)

    # Cardiovascular screening
    if patient_age >= 40:
        rec = {
            "screening": "Cardiovascular risk assessment",
            "guideline": "USPSTF Grade B",
            "frequency": "Statin use: adults 40-75 with CV risk factors",
            "notes": "Calculate 10-year ASCVD risk. Lipid panel recommended.",
        }
        recommendations.append(rec)

    if patient_age >= 35 or (patient_age >= 20 and any("diabetes" in h.lower() or "hypertension" in h.lower() for h in medical_history)):
        rec = {
            "screening": "Lipid screening",
            "guideline": "USPSTF / AHA",
            "frequency": "Every 4-6 years (more frequent if abnormal or on treatment)",
            "notes": "Fasting lipid panel preferred",
        }
        recommendations.append(rec)

    # Diabetes screening
    if patient_age >= 35:
        rec = {
            "screening": "Type 2 diabetes screening",
            "guideline": "USPSTF Grade B (35-70, overweight/obese)",
            "frequency": "Every 3 years",
            "notes": "Earlier and more frequent if BMI >=25 with additional risk factors",
        }
        recommendations.append(rec)

    # Immunizations
    vaccines = []
    vaccines.append({
        "vaccine": "Influenza",
        "recommendation": "Annually for all adults",
        "notes": "Every fall/winter season",
    })

    if patient_age >= 50:
        vaccines.append({
            "vaccine": "Shingles (Shingrix)",
            "recommendation": "2 doses for adults >=50",
            "notes": "Even if prior history of shingles or Zostavax",
        })

    if patient_age >= 65:
        vaccines.append({
            "vaccine": "Pneumococcal (PCV20 or PCV15+PPSV23)",
            "recommendation": "1 dose PCV20 for adults >=65",
            "notes": "Earlier if immunocompromised or certain chronic conditions",
        })

    vaccines.append({
        "vaccine": "COVID-19",
        "recommendation": "Updated vaccine as available",
        "notes": "Per current CDC recommendations",
    })

    if patient_age >= 19 and patient_age < 27:
        vaccines.append({
            "vaccine": "HPV",
            "recommendation": "Complete series if not previously vaccinated",
            "notes": "Shared decision for ages 27-45",
        })

    vaccines.append({
        "vaccine": "Tdap/Td",
        "recommendation": "Td booster every 10 years; Tdap once if not previously received",
        "notes": "Tdap recommended during each pregnancy (27-36 weeks)",
    })

    # Mental health screening
    mental_health = []
    if patient_age >= 12:
        mental_health.append({
            "screening": "Depression screening (PHQ-9)",
            "guideline": "USPSTF Grade B",
            "frequency": "Periodically (at least annually in primary care)",
        })

    if patient_age >= 18:
        mental_health.append({
            "screening": "Unhealthy alcohol use screening (AUDIT-C)",
            "guideline": "USPSTF Grade B",
            "frequency": "Periodically",
        })

    return {
        "patient_age": patient_age,
        "patient_sex": sex,
        "screening_recommendations": recommendations,
        "potentially_overdue": overdue if overdue else ["No screenings flagged as overdue (limited data)"],
        "immunization_recommendations": vaccines,
        "mental_health_screening": mental_health,
        "total_recommendations": len(recommendations) + len(vaccines) + len(mental_health),
        "note": "Recommendations based on USPSTF and CDC guidelines. Individual risk factors may modify recommendations.",
    }
