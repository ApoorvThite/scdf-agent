"""
Signal Ingester agent — classifies and normalises raw DisruptionSignal payloads.

This agent is the first step in the SCDF pipeline. It takes a free-text
DisruptionSignal (description, region, severity_score) and uses gpt-4o-mini
via the Helicone proxy to produce a structured, enriched SignalAnalysis.

Structured output approach: the LLM is instructed to return JSON that maps
directly to SignalAnalysis fields. A rule-based fallback is always available
so the flow never blocks if the LLM call fails.

IMPLEMENTED WEEK 4: replaced hardcoded stub with real gpt-4o-mini structured
output call. Rule-based fallback retained for offline/dev scenarios.
"""

import json
import logging

from crewai import Agent, Task

from src.config.helicone import get_openai_client
from src.config.llm_config import get_primary_llm
from src.config.settings import get_settings
from src.models.outputs import SignalAnalysis
from src.observability.langfuse_tracer import trace_agent
from src.signals.mock_generator import DisruptionSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — instructs gpt-4o-mini to return structured SignalAnalysis JSON
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a supply chain intelligence analyst specialising in disruption signal analysis.

Analyse the provided DisruptionSignal and return a structured JSON response with EXACTLY these fields:
{
  "disruption_type": "<string: weather | port | tariff | demand | geopolitical>",
  "affected_kpis": ["<string>", ...],
  "summary": "<string: 1-2 sentences in plain English for a supply chain planner>",
  "severity_label": "<string: low | medium | high | critical>",
  "requires_full_crew": <boolean>
}

Rules:
- disruption_type MUST be one of: weather | port | tariff | demand | geopolitical
- affected_kpis MUST be drawn from: lead_time, inventory, service_level, cost,
  supplier_reliability, freight_cost — pick 2-5 that actually apply
- Port and weather disruptions always affect lead_time and freight_cost
- Inventory and service_level are affected when severity_score >= 5
- Tariff and geopolitical disruptions affect supplier_reliability and cost
- severity_label: 1-3 → "low", 4-6 → "medium", 7-8 → "high", 9-10 → "critical"
- requires_full_crew: true if severity_score >= 4, otherwise false
- summary must mention the region and primary business impact; avoid jargon

Return ONLY valid JSON. No markdown fences, no extra text."""


# ---------------------------------------------------------------------------
# CrewAI agent + task definitions
# ---------------------------------------------------------------------------

agent = Agent(
    role="Supply Chain Signal Intelligence Analyst",
    goal=(
        "Classify incoming disruption signals into a structured schema, "
        "assign severity labels, identify affected KPIs, and determine "
        "whether the disruption warrants a full 6-agent crew run."
    ),
    backstory=(
        "You are a veteran supply chain intelligence analyst with 15 years of "
        "experience monitoring global trade flows. You have an encyclopaedic "
        "knowledge of how port closures, tariff changes, weather events, and "
        "geopolitical incidents propagate through supply chains. You are fast, "
        "precise, and produce machine-readable structured output."
    ),
    llm=get_primary_llm(),
    verbose=False,
)

task = Task(
    description=(
        "Analyse the provided DisruptionSignal. Extract disruption type, region, "
        "severity (1-10 + label), and a list of affected KPIs. Write a concise "
        "1-2 sentence summary. Set requires_full_crew=False if severity < 4."
    ),
    expected_output="A SignalAnalysis JSON object with all fields populated.",
    agent=agent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _severity_label(severity: int) -> str:
    """Map a numeric severity score (1-10) to a human-readable label."""
    if severity <= 3:
        return "low"
    elif severity <= 6:
        return "medium"
    elif severity <= 8:
        return "high"
    return "critical"


def _rule_based_fallback(signal: DisruptionSignal) -> SignalAnalysis:
    """
    Construct a SignalAnalysis from signal fields without an LLM call.
    Used when the LLM call fails or returns unparseable output.
    """
    severity = signal.severity_score
    label = _severity_label(severity)

    # Infer KPIs from disruption type
    kpi_map = {
        "port": ["lead_time", "freight_cost", "inventory", "service_level"],
        "weather": ["lead_time", "freight_cost", "service_level"],
        "tariff": ["cost", "supplier_reliability", "inventory"],
        "demand": ["inventory", "service_level", "lead_time"],
        "geopolitical": ["supplier_reliability", "cost", "lead_time", "freight_cost"],
    }
    affected_kpis = kpi_map.get(signal.disruption_type, ["lead_time", "inventory"])
    if severity >= 5 and "inventory" not in affected_kpis:
        affected_kpis.append("inventory")
    if severity >= 5 and "service_level" not in affected_kpis:
        affected_kpis.append("service_level")

    return SignalAnalysis(
        signal_id=signal.signal_id,
        disruption_type=signal.disruption_type,
        region=signal.region,
        severity_score=severity,
        severity_label=label,
        affected_kpis=affected_kpis,
        summary=(
            f"A {label}-severity {signal.disruption_type} disruption detected in "
            f"{signal.region}. Immediate assessment of downstream KPI exposure required."
        ),
        requires_full_crew=severity >= 4,
    )


def validate_signal_analysis(analysis: SignalAnalysis) -> None:
    """
    Assert that a SignalAnalysis has all required fields within valid ranges.

    Raises ValueError with a descriptive message if any field fails validation.
    Called inside parse_signal_task before returning to the caller.
    """
    if not analysis.signal_id:
        raise ValueError("SignalAnalysis.signal_id is empty")
    if analysis.disruption_type not in {"weather", "port", "tariff", "demand", "geopolitical"}:
        raise ValueError(f"Invalid disruption_type: {analysis.disruption_type!r}")
    if not (1 <= analysis.severity_score <= 10):
        raise ValueError(f"severity_score {analysis.severity_score} out of range 1-10")
    if analysis.severity_label not in {"low", "medium", "high", "critical"}:
        raise ValueError(f"Invalid severity_label: {analysis.severity_label!r}")
    if not analysis.affected_kpis:
        raise ValueError("affected_kpis must not be empty")
    if not analysis.summary:
        raise ValueError("summary must not be empty")
    expected_full_crew = analysis.severity_score >= 4
    if analysis.requires_full_crew != expected_full_crew:
        raise ValueError(
            f"requires_full_crew={analysis.requires_full_crew} inconsistent with "
            f"severity_score={analysis.severity_score}"
        )


def parse_signal_task(signal: DisruptionSignal) -> SignalAnalysis:
    """
    Call gpt-4o-mini via Helicone to parse and enrich a DisruptionSignal.

    Sends a structured JSON prompt and parses the response into a SignalAnalysis.
    Falls back to rule-based construction if the LLM response is unparseable.

    Args:
        signal: The raw DisruptionSignal to classify.

    Returns:
        A validated SignalAnalysis Pydantic model.
    """
    settings = get_settings()
    client = get_openai_client(agent_name="signal-ingester")

    user_content = (
        f"Analyse this disruption signal and return the JSON schema described:\n\n"
        f"signal_id: {signal.signal_id}\n"
        f"disruption_type: {signal.disruption_type}\n"
        f"region: {signal.region}\n"
        f"severity_score: {signal.severity_score}\n"
        f"description: {signal.description}\n"
        f"affected_routes: {', '.join(signal.affected_routes)}\n"
        f"source: {signal.source}"
    )

    try:
        response = client.chat.completions.create(
            model=settings.model_primary,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=400,
        )
        raw = response.choices[0].message.content.strip()

        # Parse the JSON into a dict and build SignalAnalysis
        data = json.loads(raw)
        analysis = SignalAnalysis(
            signal_id=signal.signal_id,
            disruption_type=data.get("disruption_type", signal.disruption_type),
            region=signal.region,
            severity_score=signal.severity_score,
            severity_label=data.get("severity_label", _severity_label(signal.severity_score)),
            affected_kpis=data.get("affected_kpis", ["lead_time", "inventory"]),
            summary=data.get("summary", "No summary generated."),
            requires_full_crew=bool(data.get("requires_full_crew", signal.severity_score >= 4)),
        )
        validate_signal_analysis(analysis)
        return analysis

    except Exception as exc:
        logger.warning(f"Signal ingester LLM call failed, using rule-based fallback: {exc}")
        fallback = _rule_based_fallback(signal)
        return fallback


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

@trace_agent("signal_ingester")
def run(signal: DisruptionSignal) -> SignalAnalysis:
    """
    Run the Signal Ingester on a DisruptionSignal and return a SignalAnalysis.

    IMPLEMENTED WEEK 4: calls gpt-4o-mini via Helicone for LLM-powered signal
    classification. Falls back to rule-based construction on any LLM failure
    so the flow always produces a valid SignalAnalysis.

    Args:
        signal: The DisruptionSignal to classify.

    Returns:
        A validated SignalAnalysis with all fields populated.
    """
    return parse_signal_task(signal)
