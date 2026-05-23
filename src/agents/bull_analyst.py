"""
Bull Analyst agent — argues the optimistic recovery scenario with evidence.

Uses gpt-4o (debate LLM) — one of only two agents granted the premium model.
Week 2: returns a hardcoded AnalystPosition with a confident optimistic thesis.
# TODO WEEK 5: Replace stub with real LLM debate call.
#              Wire in: ScenarioSet + ImpactAnalysis → gpt-4o structured prompt →
#              adversarial argument construction favouring P90 scenario.
"""

from crewai import Agent, Task

from src.config.llm_config import get_debate_llm
from src.models.outputs import AnalystPosition
from src.observability.langfuse_tracer import trace_agent
from src.signals.mock_generator import DisruptionSignal

agent = Agent(
    role="Optimistic Supply Chain Risk Analyst",
    goal=(
        "Construct the strongest possible evidence-backed case for the optimistic "
        "recovery scenario. Challenge bear assumptions, identify underestimated "
        "resilience factors, and advocate for the P90 best-case planning horizon."
    ),
    backstory=(
        "You are a supply chain optimist with a track record of identifying "
        "market recoveries that pessimists missed. You believe in the power of "
        "adaptive organisations to rapidly re-route, substitute, and recover. "
        "You back your arguments with historical precedents and data."
    ),
    llm=get_debate_llm(),
    verbose=False,
)

task = Task(
    description=(
        "Review the ScenarioSet and ImpactAnalysis. Build the bull case: "
        "argue that the P90 (best-case) scenario is most likely. Provide "
        "4-5 specific evidence points. State what would invalidate your position."
    ),
    expected_output="An AnalystPosition JSON with position='bull'.",
    agent=agent,
)


@trace_agent("bull_analyst")
def run(signal: DisruptionSignal) -> AnalystPosition:
    """
    Generate the bull analyst's optimistic position.

    Week 2 stub — returns hardcoded bullish thesis with 4 evidence points.
    The real week-5 implementation will receive actual scenario + impact data
    and engage in a structured adversarial debate with the bear analyst.
    """
    return AnalystPosition(
        position="bull",
        signal_id=signal.signal_id,
        thesis=(
            "Historical data shows Asia-Pacific port disruptions resolve within "
            "2 weeks in 73% of comparable cases when alternative routing capacity "
            "is available. With Port of Busan and Ningbo operating at 90% capacity, "
            "supply chain recovery will outpace the bear scenario's projections."
        ),
        key_evidence=[
            "Port of Kaohsiung 2022 strike resolved in 18 days — within our P90 window",
            "Current Busan capacity utilisation at 87% — sufficient to absorb rerouted volume",
            "3 major carriers have confirmed blank sailing adjustments within 72 hours",
            "Regional safety stock across top-20 SKUs covers 11 days of demand — buffer intact",
        ],
        recommended_scenario="P90 (best case)",
        confidence=0.74,
        dissenting_risk=(
            "If a secondary labour dispute activates at Port of Busan simultaneously, "
            "alternative routing capacity collapses and the P10 scenario becomes likely."
        ),
    )
