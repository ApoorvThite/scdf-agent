"""
Bear Analyst agent — argues the worst-case scenario and identifies tail risks.

Uses gpt-4o (debate LLM) — one of only two agents granted the premium model.
Week 2: returns a hardcoded AnalystPosition with a cautious bearish thesis.
# TODO WEEK 5: Replace stub with real LLM debate call.
#              Wire in: ScenarioSet + ImpactAnalysis + bull_position →
#              gpt-4o structured prompt that explicitly rebuts the bull analyst's
#              position and escalates tail-risk scenarios.
"""

from crewai import Agent, Task

from src.config.llm_config import get_debate_llm
from src.models.outputs import AnalystPosition
from src.observability.langfuse_tracer import trace_agent
from src.signals.mock_generator import DisruptionSignal

agent = Agent(
    role="Pessimistic Supply Chain Risk Analyst",
    goal=(
        "Surface the worst-case risks that optimists overlook. Stress-test "
        "the bull case, identify cascading failure modes, and advocate for "
        "the P10 planning horizon when tail risks are non-trivial."
    ),
    backstory=(
        "You are a supply chain risk specialist who has navigated the 2011 "
        "Fukushima crisis, the 2021 Suez Canal blockage, and the 2022 Shanghai "
        "lockdowns. You have seen firsthand how quickly 'temporary' disruptions "
        "cascade into multi-month crises. You argue with rigour and humility."
    ),
    llm=get_debate_llm(),
    verbose=False,
)

task = Task(
    description=(
        "Review the ScenarioSet, ImpactAnalysis, and bull analyst's position. "
        "Build the bear case: argue that the P10 (worst-case) scenario deserves "
        "a higher planning weight. Provide 4-5 specific risk factors. "
        "State what would invalidate your position."
    ),
    expected_output="An AnalystPosition JSON with position='bear'.",
    agent=agent,
)


@trace_agent("bear_analyst")
def run(signal: DisruptionSignal) -> AnalystPosition:
    """
    Generate the bear analyst's pessimistic position.

    Week 2 stub — returns hardcoded bearish thesis with 4 evidence points.
    The real week-5 implementation will receive actual scenario + impact data
    and debate the bull analyst's position in a structured adversarial format.
    """
    return AnalystPosition(
        position="bear",
        signal_id=signal.signal_id,
        thesis=(
            "The bull case systematically underestimates secondary congestion effects. "
            "When primary port capacity drops by 30%+, alternative ports become "
            "overwhelmed within 5-7 days. Historical data for severe disruptions "
            "shows a 40% probability of escalation beyond the P50 estimate."
        ),
        key_evidence=[
            "Port of Shanghai 2022 lockdown: initial 2-week estimate extended to 6 weeks",
            "Port of Busan is already at 87% utilisation — minimal absorption capacity",
            "Carrier blank sailing announcements lag disruptions by 5-10 days on average",
            "Current safety stock covers only 11 days — insufficient if P50 resolution fails",
        ],
        recommended_scenario="P10 (worst case)",
        confidence=0.68,
        dissenting_risk=(
            "If the disruption resolves within 10 days and no secondary port "
            "congestion materialises, the bull P90 scenario becomes the right plan."
        ),
    )
