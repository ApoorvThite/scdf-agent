"""
Structured output contracts for all 6 SCDF agents.

Every agent returns one of these Pydantic models — never a plain string.
These are the single source of truth for inter-agent data flow.
"""

from pydantic import BaseModel, Field


class SignalAnalysis(BaseModel):
    """Output of the Signal Ingester agent."""

    signal_id: str = Field(..., description="UUID of the originating DisruptionSignal")
    disruption_type: str = Field(
        ..., description="Classified type: weather | port | tariff | demand | geopolitical"
    )
    region: str = Field(..., description="Geographic region of the disruption")
    severity_score: int = Field(..., description="Numeric severity 1-10", ge=1, le=10)
    severity_label: str = Field(
        ..., description="Human label: low | medium | high | critical"
    )
    affected_kpis: list[str] = Field(
        ..., description="KPIs impacted e.g. ['lead_time', 'inventory', 'service_level']"
    )
    summary: str = Field(..., description="1-2 sentence plain-English summary of the disruption")
    requires_full_crew: bool = Field(
        ..., description="False when severity < 4 — triggers the fast path"
    )


class Scenario(BaseModel):
    """A single P10 / P50 / P90 probabilistic scenario."""

    label: str = Field(..., description="P10 (worst case) | P50 (base case) | P90 (best case)")
    probability: float = Field(..., description="Probability weight 0.0-1.0", ge=0.0, le=1.0)
    description: str = Field(..., description="Narrative description of the scenario")
    inventory_impact_pct: float = Field(
        ..., description="Expected percentage change in inventory levels"
    )
    lead_time_impact_days: int = Field(
        ..., description="Additional lead time days caused by the disruption"
    )
    service_level_impact_pct: float = Field(
        ..., description="Expected percentage change in service level"
    )
    resolution_days_estimate: int = Field(
        ..., description="Estimated days until supply chain normalises"
    )


class ScenarioSet(BaseModel):
    """Output of the Scenario Builder agent — full P10/P50/P90 forecast."""

    signal_id: str = Field(..., description="UUID of the originating DisruptionSignal")
    p10: Scenario = Field(..., description="Worst-case (10th percentile) scenario")
    p50: Scenario = Field(..., description="Base-case (50th percentile) scenario")
    p90: Scenario = Field(..., description="Best-case (90th percentile) scenario")
    forecast_confidence: float = Field(
        ..., description="Aggregate confidence in the forecast 0.0-1.0", ge=0.0, le=1.0
    )
    data_quality_note: str = Field(
        ..., description="Note on data completeness or limitations affecting the forecast"
    )


class HistoricalPrecedent(BaseModel):
    """A single retrieved record from the Qdrant disruptions collection."""

    record_id: str = Field(..., description="UUID of the Qdrant point")
    similarity_score: float = Field(
        ..., description="Cosine similarity to the query vector 0.0-1.0", ge=0.0, le=1.0
    )
    disruption_type: str = Field(..., description="Type of the historical disruption")
    region: str = Field(..., description="Region of the historical disruption")
    description: str = Field(..., description="Description of the historical event")
    resolution_days: int = Field(..., description="Actual days to resolution")
    actions_taken: list[str] = Field(..., description="Actions taken to resolve the disruption")
    outcome: str = Field(..., description="Result: successful | partial | failed")


class ImpactAnalysis(BaseModel):
    """Output of the Impact Modeler agent."""

    signal_id: str = Field(..., description="UUID of the originating DisruptionSignal")
    precedents: list[HistoricalPrecedent] = Field(
        ..., description="Top 3 similar historical disruptions retrieved from Qdrant"
    )
    kpi_impacts: dict[str, str] = Field(
        ..., description="Mapping of KPI name to impact description"
    )
    risk_level: str = Field(
        ..., description="Aggregate risk: low | medium | high | critical"
    )
    retrieval_quality: float = Field(
        ..., description="Average cosine similarity across retrieved precedents 0.0-1.0",
        ge=0.0, le=1.0,
    )


class AnalystPosition(BaseModel):
    """Output of the Bull or Bear analyst — one side of the adversarial debate."""

    position: str = Field(..., description="Which side: bull | bear")
    signal_id: str = Field(..., description="UUID of the originating DisruptionSignal")
    thesis: str = Field(..., description="2-3 sentence core argument supporting the position")
    key_evidence: list[str] = Field(
        ..., description="3-5 bullet points of supporting evidence"
    )
    recommended_scenario: str = Field(
        ..., description="Which P-scenario this analyst advocates planning for"
    )
    confidence: float = Field(
        ..., description="Analyst's confidence in their position 0.0-1.0", ge=0.0, le=1.0
    )
    dissenting_risk: str = Field(
        ..., description="The key factor that would invalidate this position"
    )


class PlaybookAction(BaseModel):
    """A single recommended action within the response playbook."""

    priority: int = Field(..., description="Execution priority — 1 is highest")
    action: str = Field(..., description="Concrete action to take")
    rationale: str = Field(..., description="Why this action is recommended")
    timeframe: str = Field(
        ..., description="When to execute: immediate | 24h | 72h | 1-week"
    )
    confidence: float = Field(
        ..., description="Confidence this action is appropriate 0.0-1.0", ge=0.0, le=1.0
    )
    cited_precedent_id: str | None = Field(
        default=None, description="UUID of the historical precedent supporting this action"
    )


class Playbook(BaseModel):
    """Final deliverable of the full crew run — ranked response playbook."""

    signal_id: str = Field(..., description="UUID of the originating DisruptionSignal")
    generated_at: str = Field(..., description="ISO 8601 UTC timestamp of generation")
    dominant_scenario: str = Field(
        ..., description="The P-scenario the crew recommends planning for"
    )
    overall_risk: str = Field(
        ..., description="Aggregate risk rating: low | medium | high | critical"
    )
    actions: list[PlaybookAction] = Field(
        ..., description="Ranked list of recommended response actions"
    )
    bull_summary: str = Field(
        ..., description="1-2 sentence summary of the bull analyst's position"
    )
    bear_summary: str = Field(
        ..., description="1-2 sentence summary of the bear analyst's position"
    )
    key_uncertainties: list[str] = Field(
        ..., description="Top 3-5 factors that could change the outcome"
    )
    ragas_context: list[str] = Field(
        ..., description="Retrieved precedent texts — used as context for RAGAS evaluation in Week 3"
    )
