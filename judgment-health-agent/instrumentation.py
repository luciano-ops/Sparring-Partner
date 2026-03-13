"""Judgment SDK instrumentation for the health agent.

Initializes the Judgeval client and tracer for monitoring agent behavior
in the Judgment dashboard. All LLM calls, tool executions, and conversation
flows are traced automatically.

Requires environment variables:
  JUDGMENT_API_KEY   - your Judgment API key
  JUDGMENT_ORG_ID    - your Judgment org ID
"""

from __future__ import annotations

import anthropic
from judgeval import Judgeval

PROJECT_NAME = "Internal-Health-Agent"

# Reads JUDGMENT_API_KEY and JUDGMENT_ORG_ID from environment automatically
judgeval_client = Judgeval(project_name=PROJECT_NAME)

tracer = judgeval_client.tracer.create()


def get_wrapped_client() -> anthropic.Anthropic:
    """Return an Anthropic client wrapped with Judgment tracing.

    The wrapped client auto-captures every API call as an LLM span
    in the Judgment trace, including token counts, latency, and model info.
    """
    return tracer.wrap(anthropic.Anthropic())
