"""
Scenario Builder agent — constructs P10/P50/P90 probabilistic scenario narratives.

# IMPLEMENTED WEEK 3: Real Prophet time-series forecasting.
#                     Generates synthetic historical series per disruption type,
#                     fits Prophet, extracts P10/P50/P90 confidence intervals.
"""

from crewai import Agent, Task

from src.config.llm_config import get_primary_llm
from src.models.outputs import ScenarioSet
from src.observability.langfuse_tracer import trace_agent
from src.signals.mock_generator import DisruptionSignal

# Regional baseline lead times (days) — used to calibrate the forecast
_REGIONAL_BASELINES: dict[str, int] = {
    "Asia-Pacific": 21,
    "Europe": 14,
    "North America": 10,
    "Middle East": 18,
    "Latin America": 16,
    "Africa": 22,
}


def _get_regional_baseline_lead_time(region: str) -> int:
    """Return the baseline ocean lead time (days) for a given region."""
    return _REGIONAL_BASELINES.get(region, 14)


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
        "resolution time estimates derived from a Prophet probabilistic forecast."
    ),
    expected_output="A ScenarioSet JSON object with p10, p50, and p90 populated.",
    agent=agent,
)


@trace_agent("scenario_builder")
def run(signal: DisruptionSignal) -> ScenarioSet:
    """
    Build P10/P50/P90 scenarios for the given signal using Prophet forecasting.

    Generates synthetic historical KPI series shaped by disruption type and
    region, fits Prophet models, and extracts probabilistic confidence intervals.
    Falls back to hardcoded stub data if Prophet fails.
    """
    from src.forecasting.prophet_engine import DisruptionForecastInput, generate_scenario_set

    try:
        forecast_input = DisruptionForecastInput(
            disruption_type=signal.disruption_type,
            region=signal.region,
            severity_score=signal.severity_score,
            baseline_lead_time_days=_get_regional_baseline_lead_time(signal.region),
            baseline_inventory_units=10_000,
            baseline_service_level_pct=95.0,
        )

        raw = generate_scenario_set(forecast_input)
        raw["signal_id"] = signal.signal_id
        return ScenarioSet(**raw)

    except Exception as exc:
        import logging
        logging.warning(f"Prophet forecast failed, using fallback stub: {exc}")
        return _stub_fallback(signal)


def _stub_fallback(signal: DisruptionSignal) -> ScenarioSet:
    """Hardcoded stub returned when Prophet is unavailable."""
    from src.models.outputs import Scenario

    return ScenarioSet(
        signal_id=signal.signal_id,
        p10=Scenario(
            label="P10 (worst case)",
            probability=0.10,
            description=(
                "Extended disruption triggers cascading stockouts across 40% of SKUs. "
                "Emergency air freight required. Major downstream customer penalties likely."
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
                "Disruption resolves within 3 weeks with partial capacity. "
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
                "Alternative routing activates within 5 days. "
                "Service levels recover to baseline within 2 weeks."
            ),
            inventory_impact_pct=-5.0,
            lead_time_impact_days=7,
            service_level_impact_pct=-4.0,
            resolution_days_estimate=14,
        ),
        forecast_confidence=0.60,
        data_quality_note="Fallback stub — Prophet unavailable.",
    )
