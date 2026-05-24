"""
Bear Analyst agent — argues the worst-case scenario and identifies tail risks.

Uses gpt-4o (debate LLM) — one of only two agents granted the premium model.
IMPLEMENTED WEEK 5: real gpt-4o structured prompt via Helicone; stub retained as
try/except fallback so the pipeline never blocks when the LLM is unavailable.
"""

import json
import logging
from typing import Optional

from crewai import Agent, Task

from src.config.helicone import get_openai_client
from src.config.llm_config import get_debate_llm
from src.config.settings import get_settings
from src.models.outputs import AnalystPosition, ImpactAnalysis, ScenarioSet
from src.observability.langfuse_tracer import trace_agent
from src.prompts import load_prompt
from src.signals.mock_generator import DisruptionSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CrewAI agent + task definitions (kept for future Crew integration)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Fallback — rule-based stub returned on any LLM failure
# ---------------------------------------------------------------------------

def _bear_fallback(signal: DisruptionSignal) -> AnalystPosition:
    """Return a conservative bear position without an LLM call."""
    return AnalystPosition(
        position="bear",
        signal_id=signal.signal_id,
        thesis=(
            "The bull case systematically underestimates secondary congestion effects. "
            "When primary capacity drops significantly, alternative routes become "
            "overwhelmed within days. Historical data for severe disruptions "
            "shows a meaningful probability of escalation beyond the P50 estimate."
        ),
        key_evidence=[
            "Historical precedents show initial disruption estimates extend in 40%+ of cases",
            "Alternative routing hubs face capacity constraints that limit absorption",
            "Carrier blank sailing announcements typically lag disruptions by 5-10 days",
            "Safety stock buffers are typically insufficient if P50 resolution slips",
        ],
        recommended_scenario="P10 (worst case)",
        confidence=0.68,
        dissenting_risk=(
            "If the disruption resolves within 10 days and no secondary port "
            "congestion materialises, the bull P90 scenario becomes the right plan."
        ),
    )


# ---------------------------------------------------------------------------
# Real LLM implementation
# ---------------------------------------------------------------------------

def run_bear_analysis_task(
    signal: DisruptionSignal,
    scenario_set: ScenarioSet,
    impact_analysis: ImpactAnalysis,
) -> AnalystPosition:
    """
    Call gpt-4o via Helicone to generate the bear analyst's adversarial position.

    Builds a rich context payload from the signal, P10 scenario, and historical
    precedents, then prompts the model to return an AnalystPosition JSON.

    Args:
        signal: The raw DisruptionSignal being analysed.
        scenario_set: P10/P50/P90 scenarios from the Prophet engine.
        impact_analysis: Historical precedents and KPI impact estimates.

    Returns:
        An AnalystPosition with position="bear".
    """
    settings = get_settings()
    client = get_openai_client(agent_name="bear-analyst")
    system_prompt = load_prompt("bear_analyst")

    # Build precedents summary for context — bear analyst focuses on failure cases
    precedents_text = "\n".join(
        f"- [{p.record_id}] {p.description} "
        f"(resolved: {p.resolution_days}d, outcome: {p.outcome}, "
        f"actions: {'; '.join(p.actions_taken[:2])})"
        for p in impact_analysis.precedents
    )

    user_content = (
        f"DISRUPTION SIGNAL\n"
        f"Signal ID: {signal.signal_id}\n"
        f"Type: {signal.disruption_type}\n"
        f"Region: {signal.region}\n"
        f"Severity: {signal.severity_score}/10\n"
        f"Description: {signal.description}\n"
        f"Affected Routes: {', '.join(signal.affected_routes)}\n\n"
        f"SCENARIO SET\n"
        f"P10 (worst case): {scenario_set.p10.description}\n"
        f"  → lead time +{scenario_set.p10.lead_time_impact_days}d, "
        f"inventory {scenario_set.p10.inventory_impact_pct:+.1f}%, "
        f"service level {scenario_set.p10.service_level_impact_pct:+.1f}%, "
        f"resolution {scenario_set.p10.resolution_days_estimate}d\n"
        f"P50 (base case): {scenario_set.p50.description}\n"
        f"  → lead time +{scenario_set.p50.lead_time_impact_days}d, "
        f"inventory {scenario_set.p50.inventory_impact_pct:+.1f}%, "
        f"service level {scenario_set.p50.service_level_impact_pct:+.1f}%, "
        f"resolution {scenario_set.p50.resolution_days_estimate}d\n"
        f"P90 (best case): {scenario_set.p90.description}\n"
        f"  → lead time +{scenario_set.p90.lead_time_impact_days}d, "
        f"inventory {scenario_set.p90.inventory_impact_pct:+.1f}%, "
        f"service level {scenario_set.p90.service_level_impact_pct:+.1f}%, "
        f"resolution {scenario_set.p90.resolution_days_estimate}d\n\n"
        f"HISTORICAL PRECEDENTS (from Qdrant)\n"
        f"{precedents_text}\n\n"
        f"KPI IMPACTS\n"
        + "\n".join(f"- {k}: {v}" for k, v in impact_analysis.kpi_impacts.items())
        + f"\n\nAggregate risk level: {impact_analysis.risk_level}\n\n"
        f"Build the strongest possible bear (pessimistic) case, focusing on "
        f"tail risks and cascading failure modes. "
        f"Return AnalystPosition JSON with position='bear'."
    )

    try:
        response = client.chat.completions.create(
            model=settings.model_debate,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=700,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)

        # Clamp confidence to valid range
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.68))))

        # Force position to "bear" — model must not recommend P90
        recommended = data.get("recommended_scenario", "P10 (worst case)")
        if "P90" in recommended:
            # Bear analyst must not recommend P90; demote to P50
            recommended = "P50 (base case)"

        return AnalystPosition(
            position="bear",
            signal_id=signal.signal_id,
            thesis=data.get("thesis", "Tail risks suggest planning for P10 scenario."),
            key_evidence=data.get("key_evidence", ["Historical escalation patterns warrant caution."]),
            recommended_scenario=recommended,
            confidence=confidence,
            dissenting_risk=data.get("dissenting_risk", "Rapid resolution would invalidate this position."),
        )

    except Exception as exc:
        logger.warning(f"Bear analyst LLM call failed, using fallback: {exc}")
        return _bear_fallback(signal)


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

@trace_agent("bear_analyst")
def run(
    signal: DisruptionSignal,
    scenario_set: Optional[ScenarioSet] = None,
    impact_analysis: Optional[ImpactAnalysis] = None,
) -> AnalystPosition:
    """
    Generate the bear analyst's pessimistic adversarial position.

    IMPLEMENTED WEEK 5: calls gpt-4o via Helicone with signal + scenario +
    precedent context. Falls back to a rule-based stub on any LLM failure.

    Args:
        signal: The DisruptionSignal being processed.
        scenario_set: P10/P50/P90 scenarios; falls back to stub if None.
        impact_analysis: Historical precedents; falls back to stub if None.

    Returns:
        An AnalystPosition with position="bear".
    """
    if scenario_set is None or impact_analysis is None:
        logger.warning("bear_analyst.run() called without scenario_set/impact_analysis — using fallback")
        return _bear_fallback(signal)
    return run_bear_analysis_task(signal, scenario_set, impact_analysis)
