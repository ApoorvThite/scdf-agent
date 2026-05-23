"""
Helicone proxy client factory.

Usage:
    from src.config.helicone import get_openai_client

    # Basic client (no per-agent tracking)
    client = get_openai_client()

    # Per-agent cost tracking (shows up as a Helicone property filter)
    client = get_openai_client(agent_name="signal-ingester")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
    )

Every call through this client appears in the Helicone dashboard at
https://www.helicone.ai under your API key's workspace. Filter by
"Helicone-Property-Agent" to see per-agent spend.
"""

import openai
from src.config.settings import get_settings


def get_openai_client(agent_name: str | None = None) -> openai.OpenAI:
    """
    Return an OpenAI client routed through the Helicone proxy.

    Args:
        agent_name: Optional label added as ``Helicone-Property-Agent`` header.
                    Use snake_case names matching your CrewAI agent roles, e.g.
                    "signal-ingester", "scenario-builder", "bull-analyst".

    Returns:
        openai.OpenAI configured with Helicone base URL and auth headers.
    """
    settings = get_settings()

    extra_headers: dict[str, str] = {
        "Helicone-Auth": f"Bearer {settings.helicone_api_key}",
    }
    if agent_name:
        extra_headers["Helicone-Property-Agent"] = agent_name

    return openai.OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.helicone_base_url,
        default_headers=extra_headers,
    )
