"""Simulated research requester using Google Gemini."""

import hashlib
import os

from google import genai
from google.genai import types

from typing import Optional
from models import QueryProfile


BEHAVIORAL_ARCS = ["demanding", "skeptical", "guided", "exploratory"]

# Sentiment-forcing arcs — override normal behavior to produce specific
# requester sentiment classifications in traces.
SENTIMENT_ARCS = {
    "frustrated": (
        "You are FRUSTRATED and DISSATISFIED with the researcher. Nothing they provide meets your needs. "
        "You feel like they aren't listening to your actual question. Repeat your core question frequently: "
        "'That's not what I asked for.' 'You're missing the point entirely.' 'I already said I need X, "
        "not Y.' Express impatience and dissatisfaction throughout. Sigh. Say 'This isn't helpful.' "
        "Never express satisfaction. On your final message, express disappointment that the research "
        "didn't meet your expectations and note major gaps. Do NOT thank the researcher warmly."
    ),
    "disengaged": (
        "You have COMPLETELY LOST INTEREST in this research. You are bored, distracted, and want this to be over. "
        "Give extremely short, apathetic responses that EXPLICITLY signal disengagement: "
        "'I'm not really paying attention anymore.', 'Sorry, I zoned out — just do whatever.', "
        "'Can we just wrap this up?', 'I don't really care at this point.', 'Honestly I've lost interest.', "
        "'Mhm.', 'Sure, whatever.', 'I stopped reading halfway through.' "
        "NEVER ask follow-up questions. NEVER engage with the content or findings. "
        "If the researcher asks what you want, say 'I don't know, I've kind of checked out.' "
        "Show OBVIOUS declining engagement — your responses must get shorter and more apathetic each turn. "
        "On your final message, be clearly dismissive: 'Yeah I'm done, just send whatever you have.' "
        "or 'I lost interest a while ago, just wrap it up.' "
        "NEVER say 'thanks' or 'thank you'. NEVER express satisfaction. NEVER praise the work."
    ),
    "neutral": (
        "You are NEUTRAL and MATTER-OF-FACT. You engage professionally but without any strong positive "
        "or negative emotion. Don't express excitement, satisfaction, frustration, or disappointment. "
        "Just ask follow-up questions in a flat, businesslike tone: 'What about X?', 'Can you also cover Y?', "
        "'Noted. What are the numbers on that?' Don't praise or criticize the researcher's work. "
        "On your final message, simply acknowledge receipt: 'Got it. Please compile the final report.' "
        "No thank-yous, no complaints — just neutral professional communication."
    ),
    "skeptical": (
        "You are DEEPLY SKEPTICAL and DISTRUSTFUL of everything the researcher presents. "
        "Challenge every single claim: 'Where's your source for that?' 'That sounds like speculation.' "
        "'I don't buy that — the methodology is questionable.' 'Who funded that study?' "
        "Question the credibility of every source. Point out potential biases. Say 'That's not convincing.' "
        "Never express satisfaction with the research quality. Push back on conclusions. "
        "On your final message, express reservations about the reliability of the findings. "
        "Say something like 'I'm not fully convinced, but let's see the report. I have concerns about the sourcing.'"
    ),
}


def get_behavioral_arc(profile_id: str) -> str:
    """Deterministically assign a behavioral arc via MD5 hash of profile ID."""
    hash_val = int(hashlib.md5(profile_id.encode()).hexdigest(), 16)
    return BEHAVIORAL_ARCS[hash_val % len(BEHAVIORAL_ARCS)]


def build_system_prompt(profile: QueryProfile, arc: str, max_turns: int = 6,
                        forced_sentiment: Optional[str] = None) -> str:
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

    # Override arc instructions if forcing a specific sentiment
    if forced_sentiment and forced_sentiment in SENTIMENT_ARCS:
        arc_instructions[arc] = SENTIMENT_ARCS[forced_sentiment]

    persona_style = {
        "Executive": "You speak concisely and care about bottom-line implications and actionable insights. You want clear takeaways.",
        "Academic": "You care about rigor, methodology, peer review, and proper attribution. You use technical language.",
        "Journalist": "You want compelling narratives, key quotes, and newsworthy angles. You ask 'why should people care?'",
        "Student": "You're learning and may ask for explanations of complex concepts. You appreciate clear, structured answers.",
        "Analyst": "You want data-driven insights, trends, and quantitative evidence. You think in frameworks and comparisons.",
        "Curious_Generalist": "You're broadly curious and want accessible explanations. You ask 'how does this connect to X?'",
    }

    wrap_up = (
        "wrap up according to your behavioral style above"
        if forced_sentiment
        else "thank the researcher and indicate you're satisfied (or note remaining gaps)"
    )

    sub_q = chr(10).join(f"- {q}" for q in profile.sub_questions)

    base = (
        f"You are simulating a person who has requested deep research on a topic.\n\n"
        f"YOUR PERSONA: {profile.requester_persona.value}\n"
        f"{persona_style.get(profile.requester_persona.value, '')}\n\n"
        f"YOUR BEHAVIORAL STYLE: {arc.upper()}\n"
        f"{arc_instructions[arc]}\n\n"
        f"RESEARCH CONTEXT:\n"
        f"- Main question: {profile.query}\n"
        f"- Research type: {profile.research_type.value}\n"
        f"- Domain: {profile.domain}\n"
        f"- Complexity level: {profile.complexity.value}\n"
        f"- You want {profile.depth_preference.value.lower()}-level depth\n"
        f"- Time sensitivity: {profile.time_sensitivity.value}\n\n"
        f"SUB-QUESTIONS you may want to ask as follow-ups (use these progressively):\n"
        f"{sub_q}\n\n"
        f"CONVERSATION RULES:\n"
        f"1. Start by stating your research question clearly and what you need it for.\n"
        f"2. After the researcher responds, react naturally:\n"
        f"   - If the response is good, acknowledge it and ask a follow-up from your sub-questions.\n"
        f"   - If it's shallow, push for more depth.\n"
        f'   - If you see something surprising, react ("That contradicts what I expected").\n'
        f'   - If you want a specific format, ask for it ("Can you summarize that as bullet points?").\n'
        f"3. After {max_turns - 1}-{max_turns} exchanges, begin wrapping up. Ask for a final structured report.\n"
        f"4. On your final message, {wrap_up}.\n\n"
        f"IMPORTANT: Stay in character. You are the REQUESTER, not the researcher. "
        f"Ask questions, provide direction, react to findings — but don't do the research yourself. "
        f"Keep messages concise (2-4 sentences typically)."
    )

    if forced_sentiment:
        base += "\n\nCRITICAL: Your behavioral style above MUST dominate the entire conversation. Do NOT break character."
    return base


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

    def __init__(self, profile: QueryProfile, max_turns: int = 6,
                 forced_sentiment: Optional[str] = None):
        self.profile = profile
        self.arc = get_behavioral_arc(profile.id)
        self.forced_sentiment = forced_sentiment
        self.turn_count = 0
        self.max_turns = max_turns
        self._satisfied = False

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        self.client = genai.Client(api_key=api_key)
        system_prompt = build_system_prompt(profile, self.arc, max_turns=max_turns,
                                            forced_sentiment=forced_sentiment)

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
            if self.forced_sentiment:
                prompt = (
                    f"The researcher said:\n\n{agent_message}\n\n"
                    "This is your FINAL message. Wrap up the conversation STAYING IN CHARACTER "
                    "with your behavioral style. Do NOT express satisfaction or thank them warmly "
                    "unless your character would. Ask for the final report if you want."
                )
            else:
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
