"""
Impact Modeler agent — retrieves similar historical disruptions via Qdrant RAG
and synthesises KPI impact estimates.

# IMPLEMENTED WEEK 3: Real Qdrant semantic search with metadata filtering.
#                     Falls back to hardcoded stub if Qdrant is unavailable.
"""

from crewai import Agent, Task

from src.config.llm_config import get_primary_llm
from src.models.outputs import HistoricalPrecedent, ImpactAnalysis, Scenario, SignalAnalysis
from src.observability.langfuse_tracer import trace_agent
from src.signals.mock_generator import DisruptionSignal

agent = Agent(
    role="Historical Impact Intelligence Analyst",
    goal=(
        "Retrieve the three most similar historical disruptions from the "
        "Qdrant knowledge base and synthesise their outcomes into quantified "
        "KPI impact estimates for the current disruption."
    ),
    backstory=(
        "You are a supply chain historian and data analyst who has catalogued "
        "hundreds of major disruption events. You excel at pattern-matching "
        "current events against historical precedents and translating past "
        "outcomes into forward-looking KPI impact estimates."
    ),
    llm=get_primary_llm(),
    verbose=False,
)

task = Task(
    description=(
        "Perform semantic search against the Qdrant disruptions collection to "
        "retrieve the top-3 most similar historical disruptions. Synthesise "
        "their resolution patterns into KPI impact estimates and a risk level."
    ),
    expected_output="An ImpactAnalysis JSON with 3 HistoricalPrecedent objects.",
    agent=agent,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _build_kpi_impact_map(scenario: Scenario, signal: DisruptionSignal) -> dict[str, str]:
    """Build human-readable KPI impact strings from the P50 scenario."""
    lead_dir = "+" if scenario.lead_time_impact_days >= 0 else ""
    inv_dir = "+" if scenario.inventory_impact_pct >= 0 else ""
    svc_dir = "+" if scenario.service_level_impact_pct >= 0 else ""
    return {
        "lead_time": (
            f"{lead_dir}{scenario.lead_time_impact_days} days expected "
            f"(P50 base-case, {signal.disruption_type} in {signal.region})"
        ),
        "inventory": (
            f"{inv_dir}{scenario.inventory_impact_pct:.1f}% units "
            f"(P50 base-case)"
        ),
        "service_level": (
            f"{svc_dir}{scenario.service_level_impact_pct:.1f}% "
            f"service level change (P50 base-case)"
        ),
        "freight_cost": f"Spot rate premium expected on alternative routes",
        "cash_flow": f"Increased working capital requirement likely",
    }


def _severity_to_risk(severity: int) -> str:
    """Map numeric severity to a risk label."""
    if severity <= 3:
        return "low"
    elif severity <= 6:
        return "medium"
    elif severity <= 8:
        return "high"
    return "critical"


# ---------------------------------------------------------------------------
# Agent run function
# ---------------------------------------------------------------------------

@trace_agent("impact_modeler")
def run(signal: DisruptionSignal, scenario: Scenario | None = None) -> ImpactAnalysis:
    """
    Retrieve historical precedents via Qdrant semantic search and estimate KPI impacts.

    Falls back to hardcoded stub data if Qdrant is unavailable.
    Stub data is clearly labelled in the retrieval_quality score (0.0).

    Args:
        signal:   The DisruptionSignal to retrieve precedents for.
        scenario: The P50 Scenario from the ScenarioSet (for KPI impact map).
                  If None, uses generic impact descriptions.
    """
    from src.memory.qdrant_retrieval import (
        retrieve_similar_disruptions,
        retrieve_response_records,
        format_precedents,
        get_retrieval_quality_score,
    )

    try:
        disruption_records = retrieve_similar_disruptions(
            disruption_type=signal.disruption_type,
            region=signal.region,
            description=signal.description,
            severity_score=signal.severity_score,
            top_k=3,
        )

        if not disruption_records:
            raise ValueError("No records returned from Qdrant — falling back to stub")

        disruption_ids = [r.get("disruption_id", r.get("id", "")) for r in disruption_records]
        response_records = retrieve_response_records(disruption_ids)
        precedents = format_precedents(disruption_records, response_records)

    except Exception as exc:
        import logging
        logging.warning(f"Qdrant retrieval failed, using stub precedents: {exc}")
        precedents = _stub_precedents()

    # Build KPI impact map from P50 scenario if available
    if scenario is not None:
        kpi_impacts = _build_kpi_impact_map(scenario, signal)
    else:
        kpi_impacts = {
            "lead_time": f"Expected +14 to +42 days depending on resolution speed",
            "inventory": "Buffer stock depletion likely; reorder triggers probable",
            "service_level": "Risk of SLA breach within 3 weeks",
            "freight_cost": "Spot rate premium of 40-120% on alternative routes",
            "cash_flow": "Increased working capital requirement estimated",
        }

    return ImpactAnalysis(
        signal_id=signal.signal_id,
        precedents=precedents,
        kpi_impacts=kpi_impacts,
        risk_level=_severity_to_risk(signal.severity_score),
        retrieval_quality=get_retrieval_quality_score(precedents),
    )


def _stub_precedents() -> list[HistoricalPrecedent]:
    """Hardcoded fallback precedents when Qdrant is unavailable."""
    return [
        HistoricalPrecedent(
            record_id="a3f8c2d1-7e45-4b2a-9c8f-1d3e5f7a9b0c",
            similarity_score=0.0,
            disruption_type="port",
            region="Asia-Pacific",
            description=(
                "Stub fallback: Port of Kaohsiung crane operator strike — "
                "35% capacity reduction for 3 weeks."
            ),
            resolution_days=21,
            actions_taken=[
                "Activated alternative routing via Port of Busan",
                "Expedited air freight for high-priority SKUs",
                "Negotiated extended payment terms with 12 key suppliers",
            ],
            outcome="partial",
        ),
        HistoricalPrecedent(
            record_id="b7d4e9f2-3a1c-4d8e-b5f2-2c4a6b8d0e1f",
            similarity_score=0.0,
            disruption_type="port",
            region="Asia-Pacific",
            description=(
                "Stub fallback: Typhoon Haikui forces Port of Taipei closure for 11 days."
            ),
            resolution_days=14,
            actions_taken=[
                "Pre-positioned 2-week safety stock for critical components",
                "Coordinated with 3PL to expedite clearance at alternative ports",
                "Issued force majeure notifications to tier-1 customers",
            ],
            outcome="successful",
        ),
        HistoricalPrecedent(
            record_id="c1e6a4b8-9f2d-4c7a-e3b1-3d5c7e9f1a2b",
            similarity_score=0.0,
            disruption_type="port",
            region="Asia-Pacific",
            description=(
                "Stub fallback: Port of Shanghai COVID-19 lockdown reduces throughput by 45%."
            ),
            resolution_days=42,
            actions_taken=[
                "Chartered 4 additional vessels via spot market",
                "Activated near-shoring fallback for 8 product families",
                "Implemented demand rationing protocol for key accounts",
            ],
            outcome="partial",
        ),
    ]
