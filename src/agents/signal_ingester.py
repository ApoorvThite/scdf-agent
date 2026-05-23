"""
Signal Ingester agent — classifies and normalises raw DisruptionSignal payloads.

Week 2: returns hardcoded stub data to validate the data flow end-to-end.
# TODO WEEK 4: Replace stub with real LLM call that parses signal payloads,
#              deduplicates against Qdrant, and extracts structured metadata
#              including affected SKUs, supplier names, and financial exposure.
"""

from crewai import Agent, Task

from src.config.llm_config import get_primary_llm
from src.models.outputs import SignalAnalysis
from src.observability.langfuse_tracer import trace_agent
from src.signals.mock_generator import DisruptionSignal

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


@trace_agent("signal_ingester")
def run(signal: DisruptionSignal) -> SignalAnalysis:
    """
    Run the Signal Ingester on a DisruptionSignal and return a SignalAnalysis.

    Week 2 stub — returns realistic hardcoded data.
    The real week-4 implementation will call the LLM with a structured prompt.
    """
    severity = signal.severity_score
    if severity <= 3:
        label = "low"
    elif severity <= 6:
        label = "medium"
    elif severity <= 8:
        label = "high"
    else:
        label = "critical"

    return SignalAnalysis(
        signal_id=signal.signal_id,
        disruption_type=signal.disruption_type,
        region=signal.region,
        severity_score=severity,
        severity_label=label,
        affected_kpis=["lead_time", "inventory", "service_level", "freight_cost"],
        summary=(
            f"A {label}-severity {signal.disruption_type} disruption detected in "
            f"{signal.region}. Immediate assessment of downstream KPI exposure required."
        ),
        requires_full_crew=severity >= 4,
    )
