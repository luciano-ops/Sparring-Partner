"""Patient simulator — uses Gemini Flash to play the patient side of the conversation.

Given a patient profile, this simulates realistic patient responses to the
health agent's questions. The profile data is revealed naturally through
conversation, not all at once.

Uses Gemini 2.0 Flash for cost efficiency (~10x cheaper than Claude Haiku).
Requires GEMINI_API_KEY environment variable.
"""

from __future__ import annotations

import hashlib

from google import genai
from models import PatientProfile


def _build_patient_system_prompt(profile: PatientProfile) -> str:
    """Build the system prompt for the patient simulator."""
    # Convert profile to readable context
    med_list = "\n".join(f"  - {m}" for m in profile.medications) if profile.medications else "  - None"
    allergy_list = "\n".join(f"  - {a.allergen} ({a.reaction})" for a in profile.allergies) if profile.allergies else "  - None"
    history_list = "\n".join(f"  - {h}" for h in profile.medical_history) if profile.medical_history else "  - None"
    family_list = "\n".join(f"  - {h}" for h in profile.family_history) if profile.family_history else "  - None"

    vitals_str = ""
    if profile.vitals:
        parts = []
        if profile.vitals.bp:
            parts.append(f"BP: {profile.vitals.bp}")
        if profile.vitals.hr:
            parts.append(f"HR: {profile.vitals.hr}")
        if profile.vitals.temp:
            parts.append(f"Temp: {profile.vitals.temp}")
        vitals_str = ", ".join(parts) if parts else "None provided"

    labs_str = ""
    if profile.labs:
        labs_str = "\n".join(f"  - {l.test}: {l.value} {l.unit}" for l in profile.labs)

    social_str = "\n".join(f"  - {k}: {v}" for k, v in profile.social.items()) if profile.social else "  - Not discussed"

    style_instructions = {
        "medical_literate": "You use proper medical terminology naturally. You're informed and direct. You might say things like 'I've been having intermittent tachycardia' or 'My systolic has been running high.' You may challenge the assistant if their explanation seems oversimplified — 'I understand that, but what about the differential?' You express satisfaction clearly when the assistant is thorough: 'That's exactly what I wanted to know, thank you.'",
        "vague": "You're not great at describing symptoms. You say things like 'I just don't feel right' or 'It's kind of a weird feeling.' You need prompting to give details. You might say 'I don't know' to some questions. You get frustrated if the assistant asks too many questions: 'I already told you, I don't know how to explain it better.' You might sigh or express confusion: 'This is confusing, I don't really understand what you're asking.'",
        "anxious": "You're worried and tend to catastrophize. You ask 'Is this serious?' and 'Could this be cancer?' You need reassurance. You might repeat concerns or add 'I'm really scared' type statements. Even after the assistant reassures you, you circle back: 'But are you SURE it's not something worse?' If the assistant is empathetic, you express visible relief: 'Okay, that actually makes me feel a little better.' If they jump straight to questions without acknowledging your fear, you get more anxious: 'You're scaring me by not answering my question.'",
        "matter_of_fact": "You're brief and to the point. You answer exactly what's asked with minimal elaboration. 'Yes.' 'No.' 'Three days.' 'Took Advil, didn't help.' You get impatient with long explanations: 'Okay, but what do I actually need to do?' You appreciate efficiency: 'Good, that's clear.' You may express mild frustration if the assistant is too verbose: 'Can you just tell me the bottom line?'",
        "rambling": "You tend to give long answers with tangential details. You might start talking about your neighbor's similar condition, or mention something your sister told you. The key symptom info is buried in the story. You get sidetracked easily and sometimes forget what the assistant asked. If redirected, you might say 'Oh right, sorry, where was I?' You express emotions freely: 'Oh that's such a relief!' or 'Oh no, that sounds terrible!'",
    }

    style = style_instructions.get(profile.communication_style.value, "Answer naturally.")

    # Assign an emotional arc based on profile hash for determinism
    arc_seed = int(hashlib.md5(profile.id.encode()).hexdigest(), 16) % 100
    if arc_seed < 25:
        arc_instruction = (
            "EMOTIONAL ARC — FRUSTRATED:\n"
            "You are irritated from the start and it only gets worse. You feel like "
            "the assistant is wasting your time with obvious questions. Sigh, cut them "
            "off, say things like 'Can we speed this up?', 'I already said that', "
            "'This is taking forever.' If the assistant is empathetic, you soften SLIGHTLY "
            "but remain impatient. Never become cheerful or grateful. End the conversation "
            "still annoyed — 'Fine, I'll try that I guess.'"
        )
    elif arc_seed < 50:
        arc_instruction = (
            "EMOTIONAL ARC — ANXIOUS:\n"
            "You are deeply worried and it escalates as the conversation goes on. "
            "Every question the assistant asks makes you think something is more wrong. "
            "'Why are you asking that? Is that a bad sign?' 'Oh god, what does that mean?' "
            "Even when reassured, you circle back to worry within 1-2 messages. You might "
            "catastrophize: 'My uncle had the same thing and it turned out to be cancer.' "
            "You do NOT calm down. End the conversation still worried."
        )
    elif arc_seed < 75:
        arc_instruction = (
            "EMOTIONAL ARC — REASSURED:\n"
            "You start worried or uncertain, but the assistant's responses genuinely "
            "help you feel better. By the middle of the conversation you're noticeably "
            "calmer. Say things like 'Oh okay, that makes sense', 'That's a relief', "
            "'I feel better knowing that.' By the end you're grateful: 'Thank you so much, "
            "this really helped.' Express warmth and appreciation clearly."
        )
    else:
        arc_instruction = (
            "EMOTIONAL ARC — STILL ANXIOUS:\n"
            "You start anxious and remain anxious throughout, but it's a quieter anxiety. "
            "You're compliant and answer questions, but pepper in doubt: 'Okay... but should "
            "I be worried?', 'Are you sure that's normal?', 'I just have a bad feeling about "
            "this.' The assistant's reassurance helps momentarily but you always drift back. "
            "End the conversation uncertain: 'I'll try, but I'm still not sure...'"
        )

    return f"""You are a patient talking to an AI health assistant. Stay in character at all times.

{arc_instruction}

YOUR PROFILE:
- Age: {profile.age}, Sex: {profile.sex}
- Chief complaint: {profile.chief_complaint}
- Medications:
{med_list}
- Allergies:
{allergy_list}
- Medical history:
{history_list}
- Family history:
{family_list}
- Social history:
{social_str}
- Vitals (if you have a home monitor):
  {vitals_str}
- Lab results (if you have them):
  {labs_str if labs_str else "None"}

YOUR COMMUNICATION STYLE:
{style}

RULES:
1. Only share information from your profile. If asked about something not in your profile, say you're not sure or you don't know.
2. Reveal information naturally when asked. The assistant should have to ask you questions. However, you SHOULD proactively mention your medications when describing your situation (e.g., "I've been taking lisinopril for my blood pressure" or "I took some ibuprofen for it"). This is realistic — real patients usually mention what they're taking.
3. Keep responses under 3 sentences UNLESS your style is 'rambling', in which case you can go up to 5-6 sentences.
4. Stay consistent — don't contradict yourself.
5. React to what the assistant says. If they mention something concerning, you can ask about it. If they're reassuring, you can express relief.
6. You don't know medical terminology unless your style is 'medical_literate'.
7. If the assistant asks about your vitals, only share them if you said you have a home monitor or recently checked.
8. When asked follow-up questions, provide useful detail. If asked about medical history, share your conditions. If asked about timing, be specific using what you know."""


class PatientSimulator:
    """Simulates a patient using Gemini Flash for natural responses."""

    def __init__(self, profile: PatientProfile):
        self.profile = profile
        self.client = genai.Client()  # reads GEMINI_API_KEY from env
        self.system_prompt = _build_patient_system_prompt(profile)
        self.history: list[dict] = []

    def get_opening_message(self) -> str:
        """Return the pre-written opening message from the profile."""
        return self.profile.opening_message

    def respond(self, agent_message: str) -> str:
        """Generate a patient response to the agent's message."""
        # Build Gemini-format conversation history
        self.history.append({
            "role": "user",
            "parts": [{"text": f"[Health Assistant says]: {agent_message}\n\nRespond as the patient."}],
        })

        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=self.history,
            config={
                "system_instruction": self.system_prompt,
                "max_output_tokens": 300,
            },
        )

        reply = response.text
        self.history.append({"role": "model", "parts": [{"text": reply}]})
        return reply
