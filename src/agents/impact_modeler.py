"""
Impact Modeler agent — retrieves similar historical disruptions and estimates KPI impact.

Week 2: returns 3 hardcoded HistoricalPrecedent objects with real-looking record IDs.
# TODO WEEK 4: Replace stub with real Qdrant semantic search.
#              Wire in: get_embedding(signal.description) → qdrant.search(
#                  collection_name="disruptions", query_vector=embedding, limit=3
#              ) → parse ScoredPoint payloads into HistoricalPrecedent objects.
"""

from crewai import Agent, Task

from src.config.llm_config import get_primary_llm
from src.models.outputs import HistoricalPrecedent, ImpactAnalysis
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


@trace_agent("impact_modeler")
def run(signal: DisruptionSignal) -> ImpactAnalysis:
    """
    Retrieve historical precedents and estimate KPI impacts for the signal.

    Week 2 stub — returns 3 hardcoded precedents with realistic record IDs.
    The real week-4 implementation will query Qdrant with semantic search.
    """
    precedents = [
        HistoricalPrecedent(
            record_id="a3f8c2d1-7e45-4b2a-9c8f-1d3e5f7a9b0c",
            similarity_score=0.91,
            disruption_type="port",
            region="Asia-Pacific",
            description=(
                "Port of Kaohsiung crane operator strike — 35% capacity reduction "
                "for 3 weeks. Significant rerouting to Port of Busan."
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
            similarity_score=0.84,
            disruption_type="port",
            region="Asia-Pacific",
            description=(
                "Typhoon Haikui forces Port of Taipei closure for 11 days. "
                "200+ vessels rerouted to regional alternatives."
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
            similarity_score=0.77,
            disruption_type="port",
            region="Asia-Pacific",
            description=(
                "Port of Shanghai COVID-19 lockdown reduces throughput by 45% "
                "for 6 weeks. Severe container equipment imbalance."
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

    avg_similarity = sum(p.similarity_score for p in precedents) / len(precedents)

    return ImpactAnalysis(
        signal_id=signal.signal_id,
        precedents=precedents,
        kpi_impacts={
            "lead_time": "Expected +14 to +42 days depending on resolution speed",
            "inventory": "Buffer stock depletion rate 2-3× normal; reorder triggers likely",
            "service_level": "Risk of dropping below 85% SLA within 3 weeks",
            "freight_cost": "Spot rate premium of 40-120% expected on alternative routes",
            "cash_flow": "Increased working capital requirement of $2-8M estimated",
        },
        risk_level="high",
        retrieval_quality=round(avg_similarity, 3),
    )
