"""Simulated research requester using Google Gemini."""

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


def build_system_prompt(profile: QueryProfile, arc: str) -> str:
    """Build the system prompt for the requester simulator."""
    arc_instructions = {
        "demanding": (
            "You are demanding and thorough. You want exhaustive answers with maximum depth. "
            "If the researcher gives a surface-level response, push back hard: 'That's too shallow, "
            "I need more depth on X.' Keep asking for more detail, more sources, more nuance. "
            "You are not easily satisfied and expect the highest quality research."
        ),
        "skeptical": (
            "You are deeply skeptical of all claims. Question every source's methodology and credibility. "
            "Ask about potential biases, conflicts of interest, and sample sizes. Say things like "
            "'That source seems biased — do you have independent verification?' and "
            "'What's the methodology behind that claim?' Push the researcher to verify everything."
        ),
        "guided": (
            "You have a specific thesis or hypothesis you want the research to investigate. "
            "You believe the research should support or definitively refute your position. "
            "Guide the researcher toward your angle: 'I think X is actually caused by Y — can you "
            "find evidence for or against that?' Be open to being wrong but push your thesis."
        ),
        "exploratory": (
            "You are curious and open-ended. Follow interesting threads wherever they lead. "
            "Change direction when something unexpected comes up: 'Oh, that's interesting — "
            "can you explore that tangent?' You don't have a fixed goal and enjoy discovering "
            "unexpected connections. Ask broad follow-up questions."
        ),
    }

    persona_style = {
        "Executive": "You speak concisely and care about bottom-line implications and actionable insights. You want clear takeaways.",
        "Academic": "You care about rigor, methodology, peer review, and proper attribution. You use technical language.",
        "Journalist": "You want compelling narratives, key quotes, and newsworthy angles. You ask 'why should people care?'",
        "Student": "You're learning and may ask for explanations of complex concepts. You appreciate clear, structured answers.",
        "Analyst": "You want data-driven insights, trends, and quantitative evidence. You think in frameworks and comparisons.",
        "Curious_Generalist": "You're broadly curious and want accessible explanations. You ask 'how does this connect to X?'",
    }

    return f"""You are simulating a person who has requested deep research on a topic.

YOUR PERSONA: {profile.requester_persona.value}
{persona_style.get(profile.requester_persona.value, "")}

YOUR BEHAVIORAL STYLE: {arc.upper()}
{arc_instructions[arc]}

RESEARCH CONTEXT:
- Main question: {profile.query}
- Research type: {profile.research_type.value}
- Domain: {profile.domain}
- Complexity level: {profile.complexity.value}
- You want {profile.depth_preference.value.lower()}-level depth
- Time sensitivity: {profile.time_sensitivity.value}

SUB-QUESTIONS you may want to ask as follow-ups (use these progressively):
{chr(10).join(f'- {q}' for q in profile.sub_questions)}

CONVERSATION RULES:
1. Start by stating your research question clearly and what you need it for.
2. After the researcher responds, react naturally:
   - If the response is good, acknowledge it and ask a follow-up from your sub-questions.
   - If it's shallow, push for more depth.
   - If you see something surprising, react ("That contradicts what I expected").
   - If you want a specific format, ask for it ("Can you summarize that as bullet points?").
3. After 6-8 exchanges, begin wrapping up. Ask for a final structured report.
4. On your final message, thank the researcher and indicate you're satisfied (or note remaining gaps).

IMPORTANT: Stay in character. You are the REQUESTER, not the researcher. Ask questions, provide direction, react to findings — but don't do the research yourself. Keep messages concise (2-4 sentences typically)."""


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
    """Simulates a research requester using Gemini."""

    def __init__(self, profile: QueryProfile):
        self.profile = profile
        self.arc = get_behavioral_arc(profile.id)
        self.turn_count = 0
        self.max_turns = 6  # 6 requester messages = ~12 total turns
        self._satisfied = False

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        self.client = genai.Client(api_key=api_key)
        system_prompt = build_system_prompt(profile, self.arc)

        self.chat = self.client.chats.create(
            model="gemini-2.0-flash",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.8,
            ),
        )

    def get_initial_message(self) -> str:
        """Get the requester's opening research query."""
        self.turn_count += 1
        prompt = (
            "Start the conversation by stating your research question and what you need. "
            "Be specific about what kind of research output you're looking for."
        )
        response = self.chat.send_message(prompt)
        return response.text

    def respond(self, agent_message: str) -> str:
        """React to the agent's response and provide next direction."""
        self.turn_count += 1

        if self.turn_count >= self.max_turns:
            prompt = (
                f"The researcher said:\n\n{agent_message}\n\n"
                "This is your FINAL message. Wrap up the conversation: thank the researcher, "
                "note if there are any remaining gaps, and ask for the final structured report "
                "if you haven't already. Indicate clearly that you're satisfied and done."
            )
        elif self.turn_count >= self.max_turns - 1:
            prompt = (
                f"The researcher said:\n\n{agent_message}\n\n"
                "You're nearing the end of this research session. Start wrapping up — "
                "ask any final questions or request the final structured report."
            )
        else:
            prompt = (
                f"The researcher said:\n\n{agent_message}\n\n"
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
