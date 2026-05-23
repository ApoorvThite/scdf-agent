# Tiered cost strategy:
#   PRIMARY  (gpt-4o-mini) — all workhorse agents: signal ingestion, retrieval,
#            scenario building, impact modeling, playbook formatting.
#            ~20× cheaper than gpt-4o; sufficient for structured JSON output.
#   DEBATE   (gpt-4o)      — bull analyst + bear analyst only.  These agents run
#            a structured adversarial debate; stronger reasoning noticeably
#            improves argument quality and edge-case coverage.
#            Estimated extra cost: ~$0.50–1.00 per full crew run.
from crewai import LLM
from src.config.settings import get_settings


def get_primary_llm() -> LLM:
    """CrewAI LLM for all workhorse agents — gpt-4o-mini via Helicone."""
    settings = get_settings()
    return LLM(
        model=settings.model_primary,
        base_url=settings.helicone_base_url,
        api_key=settings.openai_api_key,
        extra_headers={
            "Helicone-Auth": f"Bearer {settings.helicone_api_key}",
            "Helicone-Property-Agent": "primary-llm",
            "Helicone-Property-Role": "workhorse",
        },
    )


def get_debate_llm() -> LLM:
    """CrewAI LLM for bull/bear debate agents — gpt-4o via Helicone."""
    settings = get_settings()
    return LLM(
        model=settings.model_debate,
        base_url=settings.helicone_base_url,
        api_key=settings.openai_api_key,
        extra_headers={
            "Helicone-Auth": f"Bearer {settings.helicone_api_key}",
            "Helicone-Property-Agent": "debate-llm",
            "Helicone-Property-Role": "debate",
        },
    )
