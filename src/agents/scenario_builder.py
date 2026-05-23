"""
Scenario Builder agent — constructs P10/P50/P90 probabilistic scenario narratives.

Week 2: returns hardcoded stub data representing a port closure scenario.
# TODO WEEK 4: Replace stub with a real Prophet time-series forecast.
#              Wire in: signal metadata → Prophet seasonality model →
#              P10/P50/P90 intervals → narrative generation via LLM.
"""

from crewai import Agent, Task

from src.config.llm_config import get_primary_llm
from src.models.outputs import Scenario, ScenarioSet
from src.observability.langfuse_tracer import trace_agent
from src.signals.mock_generator import DisruptionSignal

agent = Agent(
    role="Probabilistic Scenario Architect",
    goal=(
        "Build three statistically grounded P10/P50/P90 scenario narratives "
        "from a disruption signal, quantifying inventory, lead-time, and "
        "service-level impacts under each probability band."
    ),
    backstory=(
        "You combine supply chain domain knowledge with quantitative forecasting "
        "expertise. You have built probabilistic planning models for Fortune 500 "
        "manufacturers and are skilled at translating statistical outputs into "
        "actionable narrative scenarios that operations teams can act on."
    ),
    llm=get_primary_llm(),
    verbose=False,
)

task = Task(
    description=(
        "Given a SignalAnalysis, produce three scenarios (P10 worst-case, "
        "P50 base-case, P90 best-case) with quantified KPI impacts and "
        "resolution time estimates. Assign a forecast confidence score."
    ),
    expected_output="A ScenarioSet JSON object with p10, p50, and p90 populated.",
    agent=agent,
)


@trace_agent("scenario_builder")
def run(signal: DisruptionSignal) -> ScenarioSet:
    """
    Build P10/P50/P90 scenarios for the given signal.

    Week 2 stub — returns hardcoded port closure scenarios.
    The real week-4 implementation will call Prophet for data-driven forecasts.
    """
    return ScenarioSet(
        signal_id=signal.signal_id,
        p10=Scenario(
            label="P10 (worst case)",
            probability=0.10,
            description=(
                "Extended port closure lasting 6+ weeks triggers cascading stockouts "
                "across 40% of SKUs. Emergency air freight required for critical components. "
                "Major downstream customer penalties likely."
            ),
            inventory_impact_pct=-35.0,
            lead_time_impact_days=42,
            service_level_impact_pct=-28.0,
            resolution_days_estimate=56,
        ),
        p50=Scenario(
            label="P50 (base case)",
            probability=0.50,
            description=(
                "Port operations resume within 3 weeks with partial capacity. "
                "Buffer inventory absorbs first 10 days of impact. "
                "Lead times increase but service levels remain above 85%."
            ),
            inventory_impact_pct=-15.0,
            lead_time_impact_days=18,
            service_level_impact_pct=-12.0,
            resolution_days_estimate=28,
        ),
        p90=Scenario(
            label="P90 (best case)",
            probability=0.90,
            description=(
                "Alternative routing via secondary port activates within 5 days. "
                "Minimal inventory draw-down. "
                "Service levels recover to baseline within 2 weeks."
            ),
            inventory_impact_pct=-5.0,
            lead_time_impact_days=7,
            service_level_impact_pct=-4.0,
            resolution_days_estimate=14,
        ),
        forecast_confidence=0.72,
        data_quality_note=(
            "Forecast based on 60 historical analogues in Qdrant. "
            "Confidence limited by recency of comparable events."
        ),
    )
