"""
Bull Analyst agent — argues the optimistic recovery scenario with evidence.

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


# ---------------------------------------------------------------------------
# Fallback — rule-based stub returned on any LLM failure
# ---------------------------------------------------------------------------

def _bull_fallback(signal: DisruptionSignal) -> AnalystPosition:
    """Return a conservative bull position without an LLM call."""
    return AnalystPosition(
        position="bull",
        signal_id=signal.signal_id,
        thesis=(
            "Historical data shows Asia-Pacific port disruptions resolve within "
            "2 weeks in 73% of comparable cases when alternative routing capacity "
            "is available. With regional port alternatives operating near capacity, "
            "supply chain recovery will outpace the bear scenario's projections."
        ),
        key_evidence=[
            "Prior disruptions of similar severity resolved within P90 window in 70%+ of cases",
            "Regional carrier networks have demonstrated rapid blank-sailing adjustments",
            "Safety stock across key SKUs provides buffer above minimum threshold",
            "Affected parties have established contingency protocols from prior incidents",
        ],
        recommended_scenario="P90 (best case)",
        confidence=0.74,
        dissenting_risk=(
            "If secondary congestion cascades to alternative routing hubs simultaneously, "
            "absorption capacity collapses and the P10 scenario becomes likely."
        ),
    )


# ---------------------------------------------------------------------------
# Real LLM implementation
# ---------------------------------------------------------------------------

def run_bull_analysis_task(
    signal: DisruptionSignal,
    scenario_set: ScenarioSet,
    impact_analysis: ImpactAnalysis,
) -> AnalystPosition:
    """
    Call gpt-4o via Helicone to generate the bull analyst's adversarial position.

    Builds a rich context payload from the signal, P50 scenario, and historical
    precedents, then prompts the model to return an AnalystPosition JSON.

    Args:
        signal: The raw DisruptionSignal being analysed.
        scenario_set: P10/P50/P90 scenarios from the Prophet engine.
        impact_analysis: Historical precedents and KPI impact estimates.

    Returns:
        An AnalystPosition with position="bull".
    """
    settings = get_settings()
    client = get_openai_client(agent_name="bull-analyst")
    system_prompt = load_prompt("bull_analyst")

    # Build precedents summary for context
    precedents_text = "\n".join(
        f"- [{p.record_id}] {p.description} "
        f"(resolved: {p.resolution_days}d, outcome: {p.outcome})"
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
        f"resolution {scenario_set.p10.resolution_days_estimate}d\n"
        f"P50 (base case): {scenario_set.p50.description}\n"
        f"  → lead time +{scenario_set.p50.lead_time_impact_days}d, "
        f"inventory {scenario_set.p50.inventory_impact_pct:+.1f}%, "
        f"resolution {scenario_set.p50.resolution_days_estimate}d\n"
        f"P90 (best case): {scenario_set.p90.description}\n"
        f"  → lead time +{scenario_set.p90.lead_time_impact_days}d, "
        f"inventory {scenario_set.p90.inventory_impact_pct:+.1f}%, "
        f"resolution {scenario_set.p90.resolution_days_estimate}d\n\n"
        f"HISTORICAL PRECEDENTS (from Qdrant)\n"
        f"{precedents_text}\n\n"
        f"KPI IMPACTS\n"
        + "\n".join(f"- {k}: {v}" for k, v in impact_analysis.kpi_impacts.items())
        + f"\n\nAggregate risk level: {impact_analysis.risk_level}\n\n"
        f"Build the strongest possible bull (optimistic) case. "
        f"Return AnalystPosition JSON with position='bull'."
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
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.74))))

        # Force position to "bull" — model must not override this
        recommended = data.get("recommended_scenario", "P90 (best case)")
        if "P10" in recommended:
            # Bull analyst must not recommend P10; promote to P50
            recommended = "P50 (base case)"

        return AnalystPosition(
            position="bull",
            signal_id=signal.signal_id,
            thesis=data.get("thesis", "Recovery expected within P90 timeframe."),
            key_evidence=data.get("key_evidence", ["Historical recovery patterns support optimistic case."]),
            recommended_scenario=recommended,
            confidence=confidence,
            dissenting_risk=data.get("dissenting_risk", "Cascading secondary disruption could invalidate this position."),
        )

    except Exception as exc:
        logger.warning(f"Bull analyst LLM call failed, using fallback: {exc}")
        return _bull_fallback(signal)


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

@trace_agent("bull_analyst")
def run(
    signal: DisruptionSignal,
    scenario_set: Optional[ScenarioSet] = None,
    impact_analysis: Optional[ImpactAnalysis] = None,
) -> AnalystPosition:
    """
    Generate the bull analyst's optimistic adversarial position.

    IMPLEMENTED WEEK 5: calls gpt-4o via Helicone with signal + scenario +
    precedent context. Falls back to a rule-based stub on any LLM failure.

    Args:
        signal: The DisruptionSignal being processed.
        scenario_set: P10/P50/P90 scenarios; falls back to stub if None.
        impact_analysis: Historical precedents; falls back to stub if None.

    Returns:
        An AnalystPosition with position="bull".
    """
    if scenario_set is None or impact_analysis is None:
        logger.warning("bull_analyst.run() called without scenario_set/impact_analysis — using fallback")
        return _bull_fallback(signal)
    return run_bull_analysis_task(signal, scenario_set, impact_analysis)
