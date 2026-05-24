"""
Playbook Writer agent — synthesises the debate outputs into a ranked action plan.

Uses gpt-4o-mini (primary LLM) — synthesis does not require the premium model.
IMPLEMENTED WEEK 5: real gpt-4o-mini structured prompt via Helicone; stub
retained as try/except fallback so the pipeline never blocks without an LLM.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from crewai import Agent, Task

from src.config.helicone import get_openai_client
from src.config.llm_config import get_primary_llm
from src.config.settings import get_settings
from src.models.outputs import (
    AnalystPosition,
    ImpactAnalysis,
    Playbook,
    PlaybookAction,
    ScenarioSet,
)
from src.observability.langfuse_tracer import trace_agent
from src.prompts import load_prompt
from src.signals.mock_generator import DisruptionSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CrewAI agent + task definitions (kept for future Crew integration)
# ---------------------------------------------------------------------------

agent = Agent(
    role="Strategic Response Playbook Architect",
    goal=(
        "Synthesise the bull/bear debate and impact analysis into a concrete, "
        "ranked response playbook. Every action must have a clear rationale, "
        "timeframe, confidence score, and citation of supporting historical precedent."
    ),
    backstory=(
        "You are a supply chain operations strategist who translates complex "
        "analytical debates into pragmatic action plans. You have written "
        "response playbooks for Tier-1 automotive, semiconductor, and FMCG "
        "companies. You are known for concision, prioritisation, and accuracy."
    ),
    llm=get_primary_llm(),
    verbose=False,
)

task = Task(
    description=(
        "Review the bull and bear analyst positions, the scenario set, and "
        "the impact analysis. Determine the dominant planning scenario. "
        "Produce 4-6 ranked response actions with timeframes and citations."
    ),
    expected_output="A Playbook JSON with actions sorted by priority.",
    agent=agent,
)


# ---------------------------------------------------------------------------
# Dominant scenario determination
# ---------------------------------------------------------------------------

def _determine_dominant_scenario(
    bull: AnalystPosition,
    bear: AnalystPosition,
    scenario_set: ScenarioSet,
) -> str:
    """
    Select the dominant planning scenario based on analyst confidence gap.

    Formula:
      bear.confidence > bull.confidence + 0.15  → P10 (worst case)
      bull.confidence > bear.confidence + 0.15  → P90 (best case)
      otherwise                                  → P50 (base case)
    """
    if bear.confidence > bull.confidence + 0.15:
        return scenario_set.p10.label
    if bull.confidence > bear.confidence + 0.15:
        return scenario_set.p90.label
    return scenario_set.p50.label


# ---------------------------------------------------------------------------
# Fallback — rule-based stub returned on any LLM failure
# ---------------------------------------------------------------------------

def _playbook_fallback(signal: DisruptionSignal) -> Playbook:
    """Return a conservative playbook without an LLM call."""
    return Playbook(
        signal_id=signal.signal_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        dominant_scenario="P50 (base case)",
        overall_risk="high",
        actions=[
            PlaybookAction(
                priority=1,
                action=(
                    "Activate alternative routing via nearest operational port for all "
                    "Trans-Pacific Eastbound shipments within 24 hours."
                ),
                rationale=(
                    "Historical precedents show alternative port activation within 48 hours "
                    "reduces P50 lead-time impact by 35-40%."
                ),
                timeframe="immediate",
                confidence=0.88,
                cited_precedent_id=None,
            ),
            PlaybookAction(
                priority=2,
                action=(
                    "Expedite air freight for the top-15 critical SKUs with "
                    "inventory coverage below 10 days. Authorise up to $500K spend."
                ),
                rationale=(
                    "Prevents service-level breach on high-margin products. "
                    "Cost is justified given potential customer penalty exposure."
                ),
                timeframe="24h",
                confidence=0.82,
                cited_precedent_id=None,
            ),
            PlaybookAction(
                priority=3,
                action=(
                    "Issue proactive customer communication to all Tier-1 accounts "
                    "with revised lead-time estimates and recovery timeline."
                ),
                rationale=(
                    "Early transparency reduces penalty risk. Accounts notified within "
                    "72 hours accept delays at 3x higher rate than those notified late."
                ),
                timeframe="72h",
                confidence=0.91,
                cited_precedent_id=None,
            ),
            PlaybookAction(
                priority=4,
                action=(
                    "Initiate emergency safety stock audit across all distribution centres "
                    "to identify critical coverage gaps for top-50 SKUs."
                ),
                rationale=(
                    "Inventory visibility enables prioritised replenishment decisions "
                    "and prevents blind spots during extended disruption."
                ),
                timeframe="24h",
                confidence=0.85,
                cited_precedent_id=None,
            ),
            PlaybookAction(
                priority=5,
                action=(
                    "Initiate negotiations with 3 near-shore manufacturing partners "
                    "to qualify dual-source options for the top-5 affected product lines."
                ),
                rationale=(
                    "Structural resilience investment. P10 scenario probability "
                    "justifies initiating dual-source qualification now."
                ),
                timeframe="1-week",
                confidence=0.65,
                cited_precedent_id=None,
            ),
        ],
        bull_summary=(
            "Bull case: optimistic recovery scenario via alternative routing — "
            "service levels expected to hold above threshold with existing buffer."
        ),
        bear_summary=(
            "Bear case: tail risk of cascading congestion at alternative routes — "
            "potential extended disruption with service level breach."
        ),
        key_uncertainties=[
            "Alternative port utilisation trajectory over next 5-10 days",
            "Whether carrier blank sailing announcements trigger additional capacity crunch",
            "Duration of primary disruption — negotiation or resolution timeline",
            "Tier-2 supplier buffer stock levels (requires audit)",
        ],
        ragas_context=[],
    )


# ---------------------------------------------------------------------------
# Real LLM implementation
# ---------------------------------------------------------------------------

def write_playbook_task(
    signal: DisruptionSignal,
    scenario_set: ScenarioSet,
    impact_analysis: ImpactAnalysis,
    bull_position: AnalystPosition,
    bear_position: AnalystPosition,
) -> Playbook:
    """
    Call gpt-4o-mini via Helicone to synthesise the ranked response playbook.

    Combines the full debate context — signal, scenarios, precedents, bull and bear
    positions — into a single prompt and parses the structured JSON response.

    Args:
        signal: The raw DisruptionSignal being analysed.
        scenario_set: P10/P50/P90 scenarios from the Prophet engine.
        impact_analysis: Historical precedents and KPI impact estimates.
        bull_position: The optimistic AnalystPosition from the bull agent.
        bear_position: The pessimistic AnalystPosition from the bear agent.

    Returns:
        A Playbook with 5 ranked PlaybookAction items and ragas_context populated.
    """
    settings = get_settings()
    client = get_openai_client(agent_name="playbook-writer")
    system_prompt = load_prompt("playbook_writer")

    # Pre-compute dominant scenario so the prompt is consistent with our logic
    dominant_scenario = _determine_dominant_scenario(bull_position, bear_position, scenario_set)

    # Build precedent details for action citations
    precedents_text = "\n".join(
        f"- ID: {p.record_id}\n"
        f"  Description: {p.description}\n"
        f"  Resolution: {p.resolution_days}d | Outcome: {p.outcome}\n"
        f"  Actions taken: {'; '.join(p.actions_taken)}"
        for p in impact_analysis.precedents
    )

    # ragas_context is populated from precedent descriptions (ground truth for RAGAS eval)
    ragas_context = [p.description for p in impact_analysis.precedents]

    user_content = (
        f"DISRUPTION SIGNAL\n"
        f"Signal ID: {signal.signal_id}\n"
        f"Type: {signal.disruption_type} | Region: {signal.region} | Severity: {signal.severity_score}/10\n"
        f"Description: {signal.description}\n\n"
        f"SCENARIO SET\n"
        f"P10: {scenario_set.p10.label} — {scenario_set.p10.description}\n"
        f"P50: {scenario_set.p50.label} — {scenario_set.p50.description}\n"
        f"P90: {scenario_set.p90.label} — {scenario_set.p90.description}\n"
        f"Forecast confidence: {scenario_set.forecast_confidence:.2f}\n\n"
        f"HISTORICAL PRECEDENTS (available for citation)\n"
        f"{precedents_text}\n\n"
        f"BULL ANALYST POSITION (confidence: {bull_position.confidence:.2f})\n"
        f"Thesis: {bull_position.thesis}\n"
        f"Evidence: {'; '.join(bull_position.key_evidence)}\n"
        f"Recommended: {bull_position.recommended_scenario}\n"
        f"Dissenting risk: {bull_position.dissenting_risk}\n\n"
        f"BEAR ANALYST POSITION (confidence: {bear_position.confidence:.2f})\n"
        f"Thesis: {bear_position.thesis}\n"
        f"Evidence: {'; '.join(bear_position.key_evidence)}\n"
        f"Recommended: {bear_position.recommended_scenario}\n"
        f"Dissenting risk: {bear_position.dissenting_risk}\n\n"
        f"PRE-COMPUTED DOMINANT SCENARIO: {dominant_scenario}\n"
        f"(Use this exact string for the dominant_scenario field.)\n\n"
        f"Produce a 5-action response playbook. "
        f"Return Playbook JSON with exactly 5 actions."
    )

    try:
        response = client.chat.completions.create(
            model=settings.model_primary,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=1200,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)

        # Parse actions list — validate priority sequence
        raw_actions = data.get("actions", [])
        actions = []
        for i, a in enumerate(raw_actions[:5], start=1):
            cited_id = a.get("cited_precedent_id")
            # Ensure cited ID is either a valid precedent UUID or None
            valid_ids = {p.record_id for p in impact_analysis.precedents}
            if cited_id and cited_id not in valid_ids:
                cited_id = None  # Drop fabricated IDs

            actions.append(PlaybookAction(
                priority=a.get("priority", i),
                action=a.get("action", f"Action {i}"),
                rationale=a.get("rationale", "Based on scenario analysis."),
                timeframe=a.get("timeframe", "72h"),
                confidence=max(0.0, min(1.0, float(a.get("confidence", 0.75)))),
                cited_precedent_id=cited_id,
            ))

        # Pad to exactly 5 actions if the model returned fewer
        fallback_pb = _playbook_fallback(signal)
        while len(actions) < 5:
            idx = len(actions)
            actions.append(fallback_pb.actions[idx] if idx < len(fallback_pb.actions) else fallback_pb.actions[-1])

        return Playbook(
            signal_id=signal.signal_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            dominant_scenario=data.get("dominant_scenario", dominant_scenario),
            overall_risk=data.get("overall_risk", impact_analysis.risk_level),
            actions=actions[:5],
            bull_summary=data.get("bull_summary", bull_position.thesis[:100]),
            bear_summary=data.get("bear_summary", bear_position.thesis[:100]),
            key_uncertainties=data.get("key_uncertainties", ["Outcome uncertain."]),
            ragas_context=ragas_context,
        )

    except Exception as exc:
        logger.warning(f"Playbook writer LLM call failed, using fallback: {exc}")
        fallback = _playbook_fallback(signal)
        # Still populate ragas_context from precedents even in fallback
        fallback = fallback.model_copy(update={"ragas_context": ragas_context})
        return fallback


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

@trace_agent("playbook_writer")
def run(
    signal: DisruptionSignal,
    scenario_set: Optional[ScenarioSet] = None,
    impact_analysis: Optional[ImpactAnalysis] = None,
    bull_position: Optional[AnalystPosition] = None,
    bear_position: Optional[AnalystPosition] = None,
) -> Playbook:
    """
    Synthesise debate outputs into a ranked response playbook.

    IMPLEMENTED WEEK 5: calls gpt-4o-mini via Helicone when all context is
    provided. Falls back to a rule-based stub for fast-path runs (no debate).

    Args:
        signal: The DisruptionSignal being processed.
        scenario_set: P10/P50/P90 scenarios; falls back to stub if None.
        impact_analysis: Historical precedents; falls back to stub if None.
        bull_position: Bull analyst output; falls back to stub if None.
        bear_position: Bear analyst output; falls back to stub if None.

    Returns:
        A Playbook with 5 ranked actions.
    """
    if (
        scenario_set is None
        or impact_analysis is None
        or bull_position is None
        or bear_position is None
    ):
        logger.debug("playbook_writer.run() missing debate context — using fallback (fast path)")
        fallback = _playbook_fallback(signal)
        # Populate ragas_context from precedents if available
        if impact_analysis is not None:
            ragas_context = [p.description for p in impact_analysis.precedents]
            fallback = fallback.model_copy(update={"ragas_context": ragas_context})
        return fallback

    return write_playbook_task(signal, scenario_set, impact_analysis, bull_position, bear_position)
