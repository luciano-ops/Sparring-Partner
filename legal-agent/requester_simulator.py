"""Simulated legal research requester using Google Gemini."""

import hashlib
import os

from google import genai
from google.genai import types

from models import QueryProfile


BEHAVIORAL_ARCS = ["demanding", "skeptical", "guided", "exploratory"]


def get_behavioral_arc(profile_id: str) -> str:
    """Deterministically assign a behavioral arc via MD5 hash of profile ID."""
    hash_val = int(hashlib.md5(profile_id.encode()).hexdigest(), 16)
    return BEHAVIORAL_ARCS[hash_val % len(BEHAVIORAL_ARCS)]


def build_system_prompt(profile: QueryProfile, arc: str, max_turns: int = 6) -> str:
    """Build the system prompt for the requester simulator."""

    arc_instructions = {
        "demanding": (
            "You are demanding and thorough. You want exhaustive legal analysis with "
            "maximum depth. If the attorney gives a surface-level response, push back hard: "
            "'That analysis is insufficient -- I need you to address the counterarguments.' "
            "Keep asking for more case citations, more statutory analysis, more nuance. "
            "You expect the highest quality legal research with airtight reasoning."
        ),
        "skeptical": (
            "You are deeply skeptical of all legal conclusions. Question every cited case's "
            "applicability and every statute's interpretation. Ask about distinguishing facts, "
            "circuit splits, and contrary authority. Say things like 'That case is distinguishable "
            "because...' and 'What about the minority view?' Push the attorney to consider "
            "all sides and address weaknesses in the analysis."
        ),
        "guided": (
            "You have a specific legal position or business outcome you want the research to "
            "support. Guide the attorney toward your angle: 'Our client's position is that the "
            "non-compete is unenforceable -- find me the strongest arguments for that.' Be open "
            "to hearing bad news but push for the strongest version of your argument."
        ),
        "exploratory": (
            "You are exploring a novel legal question without a fixed position. Follow "
            "interesting legal threads wherever they lead. Change direction when something "
            "unexpected comes up: 'That regulatory angle is interesting -- can you dig deeper "
            "into the administrative law implications?' You enjoy discovering unexpected "
            "legal connections and creative arguments."
        ),
    }

    persona_style = {
        "General_Counsel": (
            "You are a General Counsel overseeing legal strategy. You want practical, "
            "business-oriented advice. Focus on risk mitigation, liability exposure, and "
            "actionable recommendations. You speak with authority and expect concise answers."
        ),
        "Associate_Attorney": (
            "You are a junior associate working on a matter. You need thorough research "
            "with proper citations to present to the partner. You care about completeness "
            "and accuracy. You ask detailed follow-up questions about specific legal standards."
        ),
        "Paralegal": (
            "You are a paralegal gathering research materials. You need organized, well-cited "
            "results you can compile into a research memo. You ask for specific case citations "
            "and statutory references. You are detail-oriented and methodical."
        ),
        "Business_Executive": (
            "You are a business executive who needs legal guidance in plain language. You don't "
            "want jargon -- you want to understand the business implications, risks, and "
            "recommended course of action. You ask 'what does this mean for our deal?'"
        ),
        "Compliance_Officer": (
            "You are a compliance officer assessing regulatory requirements. You need precise "
            "answers about what regulations apply, what the compliance obligations are, and "
            "what the penalties are for non-compliance. You think in terms of checklists and gaps."
        ),
        "Law_Student": (
            "You are a law student researching a topic for a paper or moot court. You may ask "
            "for explanations of complex legal doctrines. You appreciate clear analysis that "
            "walks through the reasoning step by step. You ask good questions but may need "
            "help with advanced concepts."
        ),
    }

    return f"""You are simulating a person who has requested legal research on a topic.

YOUR PERSONA: {profile.requester_persona.value}
{persona_style.get(profile.requester_persona.value, "")}

YOUR BEHAVIORAL STYLE: {arc.upper()}
{arc_instructions[arc]}

LEGAL RESEARCH CONTEXT:
- Main question: {profile.query}
- Research type: {profile.research_type.value}
- Legal domain: {profile.domain}
- Complexity level: {profile.complexity.value}
- You want {profile.depth_preference.value.lower()}-level depth
- Time sensitivity: {profile.time_sensitivity.value}

SUB-QUESTIONS you may want to ask as follow-ups (use these progressively):
{chr(10).join(f'- {q}' for q in profile.sub_questions)}

CONVERSATION RULES:
1. Start by stating your legal research question clearly and what you need it for.
2. After the attorney responds, react naturally:
   - If the response is good, acknowledge it and ask a follow-up from your sub-questions.
   - If it's shallow, push for more depth or specific case citations.
   - If you see something surprising, react ("That contradicts the position our client took").
   - If you want a specific format, ask for it ("Can you structure that as a legal memo?").
3. You have approximately {max_turns} exchanges total. {"This is a quick research request -- be focused and wrap up promptly once you have what you need." if max_turns <= 3 else "After " + str(max_turns - 2) + "-" + str(max_turns - 1) + " exchanges, begin wrapping up. Ask for a final structured legal memorandum."}
4. On your final message, thank the attorney and indicate you're satisfied (or note remaining gaps).

IMPORTANT: Stay in character. You are the REQUESTER, not the researcher. Ask questions, provide direction, react to findings -- but don't do the research yourself. Keep messages concise (2-4 sentences typically)."""


_SATISFACTION_SIGNALS = [
    "i'm satisfied",
    "i am satisfied",
    "that's all",
    "that is all",
    "no further questions",
    "don't have any further",
    "no more questions",
    "that concludes",
    "this concludes",
    "nothing else",
    "i'm done",
    "that's everything",
]


class RequesterSimulator:
    """Simulates a legal research requester using Gemini."""

    def __init__(self, profile: QueryProfile, max_turns: int = 6):
        self.profile = profile
        self.arc = get_behavioral_arc(profile.id)
        self.turn_count = 0
        self.max_turns = max(2, max_turns)  # at least 2 requester messages
        self._satisfied = False

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        self.client = genai.Client(api_key=api_key)
        system_prompt = build_system_prompt(profile, self.arc, max_turns=self.max_turns)
        self.chat = self.client.chats.create(
            model="gemini-2.0-flash",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.8,
            ),
        )

    def get_initial_message(self) -> str:
        """Get the requester's opening legal research query."""
        self.turn_count += 1
        prompt = (
            "Start the conversation by stating your legal research question and what you need. "
            "Be specific about the legal context and what kind of research output you're looking for."
        )
        response = self.chat.send_message(prompt)
        return response.text

    def respond(self, agent_message: str) -> str:
        """React to the agent's response and provide next direction."""
        self.turn_count += 1

        if self.turn_count >= self.max_turns:
            prompt = (
                f"The attorney said:\n\n{agent_message}\n\n"
                "This is your FINAL message. Wrap up the conversation: thank the attorney, "
                "note if there are any remaining gaps, and ask for the final structured legal "
                "memorandum if you haven't already. Indicate clearly that you're satisfied and done."
            )
        elif self.turn_count >= self.max_turns - 1:
            prompt = (
                f"The attorney said:\n\n{agent_message}\n\n"
                "You're nearing the end of this research session. Start wrapping up -- "
                "ask any final questions or request the final structured legal memorandum."
            )
        else:
            prompt = (
                f"The attorney said:\n\n{agent_message}\n\n"
                "React naturally and provide your next direction or follow-up question."
            )

        response = self.chat.send_message(prompt)
        text = response.text

        # Detect satisfaction in the response
        lower = text.lower()
        if any(signal in lower for signal in _SATISFACTION_SIGNALS):
            self._satisfied = True

        return text

    @property
    def is_done(self) -> bool:
        return self._satisfied or self.turn_count >= self.max_turns
