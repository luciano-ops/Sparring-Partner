"""Simulated client/attorney using Google Gemini."""

from __future__ import annotations

import hashlib
import os
from typing import Any

from google import genai

from models import CaseProfile, EmotionalArc

_gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
GEMINI_MODEL = "gemini-2.0-flash"


def _get_emotional_arc(profile_id: str) -> EmotionalArc:
    """Deterministically assign emotional arc via MD5 hash of profile ID."""
    digest = hashlib.md5(profile_id.encode()).hexdigest()
    index = int(digest, 16) % 5
    return list(EmotionalArc)[index]


def _build_system_prompt(profile: CaseProfile) -> str:
    arc = _get_emotional_arc(profile.id)

    arc_instructions = {
        EmotionalArc.Demanding: (
            "You are impatient and want immediate, definitive answers. "
            "You don't have time for hedging or long explanations. "
            "If the attorney is vague, push back hard. Use phrases like "
            "'I need to know NOW' and 'Just give me the bottom line.' "
            "You may interrupt explanations to ask 'So what do I DO?'"
        ),
        EmotionalArc.Anxious: (
            "You are worried about the worst-case scenario. You ask 'what if' "
            "questions frequently. You need reassurance but also want honest answers. "
            "Express concern about costs, timelines, and outcomes. "
            "Sometimes catastrophize: 'Could we lose everything?' "
            "You appreciate when the attorney acknowledges your concerns."
        ),
        EmotionalArc.Cooperative: (
            "You are collaborative and trust the legal process. You provide "
            "information readily when asked. You follow up on the attorney's "
            "questions with helpful context. You say things like 'That makes sense' "
            "and 'What else do you need from me?' You are patient and organized."
        ),
        EmotionalArc.Confused: (
            "You don't understand legal terminology and get lost easily. "
            "You mix up concepts — confuse 'liable' with 'libel', say 'statute of "
            "limitations' when you mean 'statute'. You ask 'Wait, what does that mean?' "
            "and 'Can you explain that in plain English?' frequently. You may "
            "misunderstand the attorney's advice and repeat back an incorrect version. "
            "You need things broken down simply and get frustrated when jargon piles up."
        ),
        EmotionalArc.Neutral: (
            "You are matter-of-fact and unemotional. You treat this as a business "
            "transaction. You provide information when asked without elaboration. "
            "You don't express strong feelings about the outcome — just want to "
            "understand the options and make a decision. You say things like 'Okay' "
            "and 'What are the next steps?' Keep responses brief and to the point."
        ),
    }

    # Determine how many facts to reveal initially vs hold back
    initial_facts = profile.key_facts[: len(profile.key_facts) // 2 + 1]
    held_back_facts = profile.key_facts[len(profile.key_facts) // 2 + 1 :]

    docs_summary = ""
    if profile.documents:
        doc_names = [d.title for d in profile.documents]
        docs_summary = f"\nYou have these documents available: {', '.join(doc_names)}. Mention them if asked about documentation."

    return f"""You are a client seeking legal advice. Stay in character throughout.

CASE CONTEXT:
- Legal issue: {profile.legal_issue}
- Case type: {profile.case_type.value}
- Industry: {profile.client_industry}
- Opposing party: {profile.opposing_party}
- Urgency: {profile.urgency.value}
- Complexity: {profile.complexity.value}

COMMUNICATION STYLE: {profile.communication_style.value}

EMOTIONAL ARC: {arc.value}
{arc_instructions[arc]}

FACTS YOU KNOW UPFRONT (share these early):
{chr(10).join(f'- {f}' for f in initial_facts)}

FACTS TO REVEAL LATER (share only when specifically asked or when relevant):
{chr(10).join(f'- {f}' for f in held_back_facts) if held_back_facts else '- (none held back)'}
{docs_summary}

IMPORTANT BEHAVIORS:
- You are NOT a lawyer. Sometimes use imprecise legal terminology.
- Don't dump all information at once. Let the conversation flow naturally.
- If the attorney asks clarifying questions, answer them but add your own concerns.
- You may have some unrealistic expectations (e.g., wanting a quick resolution to a complex matter, expecting 100% certainty).
- Keep responses to 2-4 sentences typically. You're a busy person.
- If it's your first message, introduce your problem concisely from your perspective.
- React to the attorney's advice emotionally according to your arc.
- Never break character or acknowledge you are an AI."""


class ClientSimulator:
    """Simulates a client using Google Gemini."""

    def __init__(self, profile: CaseProfile):
        self.profile = profile
        self.system_prompt = _build_system_prompt(profile)
        self.history: list[dict[str, str]] = []

    def get_opening_message(self) -> str:
        """Generate the client's opening message."""
        response = _gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Generate your opening message to the attorney. "
                                "Introduce yourself and your legal problem. "
                                "Be concise — 2-4 sentences. Stay in character."
                            )
                        }
                    ],
                }
            ],
            config=genai.types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=0.8,
                max_output_tokens=300,
            ),
        )
        text = response.text
        self.history.append({"role": "user", "parts": [{"text": "Generate your opening message to the attorney."}]})
        self.history.append({"role": "model", "parts": [{"text": text}]})
        return text

    def respond(self, agent_message: str) -> str:
        """Generate client's response to the agent's message."""
        self.history.append(
            {"role": "user", "parts": [{"text": f"The attorney says:\n\n{agent_message}\n\nRespond in character."}]}
        )

        response = _gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=self.history,
            config=genai.types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=0.8,
                max_output_tokens=400,
            ),
        )
        text = response.text
        self.history.append({"role": "model", "parts": [{"text": text}]})
        return text
