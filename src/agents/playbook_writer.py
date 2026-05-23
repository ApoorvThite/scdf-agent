"""
Playbook Writer agent — synthesises the debate outputs into a ranked action plan.

Week 2: returns a hardcoded Playbook with 4 PlaybookAction items.
# TODO WEEK 5: Replace stub with real LLM synthesis call.
#              Wire in: ScenarioSet + ImpactAnalysis + bull_position + bear_position →
#              gpt-4o-mini structured prompt that weighs debate outcomes,
#              cites historical precedents, and ranks actions by urgency.
"""

from datetime import datetime, timezone

from crewai import Agent, Task

from src.config.llm_config import get_primary_llm
from src.models.outputs import Playbook, PlaybookAction
from src.observability.langfuse_tracer import trace_agent
from src.signals.mock_generator import DisruptionSignal

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


@trace_agent("playbook_writer")
def run(signal: DisruptionSignal) -> Playbook:
    """
    Synthesise debate outputs into a ranked response playbook.

    Week 2 stub — returns a 4-action playbook with realistic content.
    The real week-5 implementation will synthesise real bull/bear debate outputs
    and cite specific HistoricalPrecedent record IDs.
    """
    return Playbook(
        signal_id=signal.signal_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        dominant_scenario="P50 (base case)",
        overall_risk="high",
        actions=[
            PlaybookAction(
                priority=1,
                action=(
                    "Activate alternative routing via Port of Busan for all "
                    "Trans-Pacific Eastbound shipments within 24 hours."
                ),
                rationale=(
                    "Historical precedents show Busan activation within 48 hours "
                    "reduces P50 lead-time impact from 18 to 11 days."
                ),
                timeframe="immediate",
                confidence=0.88,
                cited_precedent_id="a3f8c2d1-7e45-4b2a-9c8f-1d3e5f7a9b0c",
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
                cited_precedent_id="b7d4e9f2-3a1c-4d8e-b5f2-2c4a6b8d0e1f",
            ),
            PlaybookAction(
                priority=3,
                action=(
                    "Issue proactive customer communication to all Tier-1 accounts "
                    "with revised lead-time estimates (+14 days) and recovery timeline."
                ),
                rationale=(
                    "Early transparency reduces penalty risk and preserves customer "
                    "relationships. Accounts notified within 72 hours accept delays "
                    "at 3× higher rate than those notified late."
                ),
                timeframe="72h",
                confidence=0.91,
                cited_precedent_id=None,
            ),
            PlaybookAction(
                priority=4,
                action=(
                    "Initiate negotiations with 3 near-shore manufacturing partners "
                    "to qualify dual-source options for the top-5 affected product lines."
                ),
                rationale=(
                    "Structural resilience investment. P10 scenario probability "
                    "at 10% justifies initiating dual-source qualification now "
                    "to reduce exposure in future disruptions."
                ),
                timeframe="1-week",
                confidence=0.65,
                cited_precedent_id="c1e6a4b8-9f2d-4c7a-e3b1-3d5c7e9f1a2b",
            ),
        ],
        bull_summary=(
            "Bull case: P90 resolution in 14 days via Busan rerouting — "
            "service levels hold above 90% with existing safety stock."
        ),
        bear_summary=(
            "Bear case: P10 escalation risk if Busan congestion materialises — "
            "potential 6-week disruption with service level breach below 75%."
        ),
        key_uncertainties=[
            "Busan port utilisation trajectory over next 5-10 days",
            "Whether carrier blank sailing announcements trigger additional capacity crunch",
            "Duration of primary port disruption — union negotiation progress",
            "Tier-2 supplier buffer stock levels (unknown, requires audit)",
        ],
        ragas_context=[
            (
                "Port of Kaohsiung crane operator strike — 35% capacity reduction for "
                "3 weeks. Activated Busan routing. Partial outcome. Resolution: 21 days."
            ),
            (
                "Typhoon Haikui Port of Taipei closure — 11 days. Pre-positioned safety "
                "stock. Force majeure issued. Successful outcome. Resolution: 14 days."
            ),
            (
                "Port of Shanghai COVID-19 lockdown — 45% throughput reduction for 6 weeks. "
                "Spot vessel charter + near-shoring activation. Partial outcome. 42 days."
            ),
        ],
    )
