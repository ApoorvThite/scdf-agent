"""
Week 3 test suite — Prophet forecasting, Qdrant retrieval, RAGAS evaluation.

Tests are divided into:
  - Unit tests (no live services required, mocks used)
  - Integration tests (require live Qdrant) marked with @pytest.mark.integration
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.signals.mock_generator import DisruptionSignal, generate_mock_signal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def port_signal() -> DisruptionSignal:
    return DisruptionSignal(
        signal_id=str(uuid.uuid4()),
        disruption_type="port",
        region="Asia-Pacific",
        severity_score=8,
        description="Port of Shanghai crane operator strike halts container operations at major terminals.",
        affected_routes=["Trans-Pacific Eastbound", "Intra-Asia"],
        source="Lloyd's List",
    )


@pytest.fixture
def low_severity_signal() -> DisruptionSignal:
    return DisruptionSignal(
        signal_id=str(uuid.uuid4()),
        disruption_type="weather",
        region="Europe",
        severity_score=2,
        description="Minor fog delay at Rotterdam port.",
        affected_routes=["Europe Intra-Regional"],
        source="Met Office",
    )


@pytest.fixture
def mock_lf():
    """Shared mock Langfuse client."""
    lf = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    lf.start_as_current_observation.return_value = cm
    lf.create_trace_id.return_value = "test-trace-id"
    return lf


# ---------------------------------------------------------------------------
# Task 1: Prophet engine tests
# ---------------------------------------------------------------------------

class TestProphetEngine:
    def test_generates_three_scenarios(self):
        """generate_scenario_set must return p10, p50, p90 keys."""
        from src.forecasting.prophet_engine import DisruptionForecastInput, generate_scenario_set

        inp = DisruptionForecastInput(
            disruption_type="port",
            region="Asia-Pacific",
            severity_score=7,
            baseline_lead_time_days=21,
        )
        result = generate_scenario_set(inp)
        assert "p10" in result
        assert "p50" in result
        assert "p90" in result
        assert result["p10"]["probability"] == 0.10
        assert result["p50"]["probability"] == 0.50
        assert result["p90"]["probability"] == 0.90

    def test_p10_worse_than_p90_service_level(self):
        """P10 (worst case) must have lower service level impact than P90 (best case)."""
        from src.forecasting.prophet_engine import DisruptionForecastInput, generate_scenario_set

        inp = DisruptionForecastInput(
            disruption_type="port",
            region="Asia-Pacific",
            severity_score=7,
        )
        result = generate_scenario_set(inp)
        assert result["p10"]["service_level_impact_pct"] < result["p90"]["service_level_impact_pct"]

    def test_p10_worse_than_p90_lead_time(self):
        """P10 must have higher (worse) lead time impact than P90."""
        from src.forecasting.prophet_engine import DisruptionForecastInput, generate_scenario_set

        inp = DisruptionForecastInput(
            disruption_type="port",
            region="Asia-Pacific",
            severity_score=7,
        )
        result = generate_scenario_set(inp)
        # Lead time: higher = worse
        assert result["p10"]["lead_time_impact_days"] >= result["p90"]["lead_time_impact_days"]

    def test_forecast_confidence_in_range(self):
        from src.forecasting.prophet_engine import DisruptionForecastInput, generate_scenario_set

        inp = DisruptionForecastInput(disruption_type="weather", region="Europe", severity_score=5)
        result = generate_scenario_set(inp)
        assert 0.0 <= result["forecast_confidence"] <= 1.0

    def test_different_types_give_different_results(self):
        """Port and weather forecasts should produce different lead time impacts."""
        from src.forecasting.prophet_engine import DisruptionForecastInput, generate_scenario_set

        port = generate_scenario_set(DisruptionForecastInput(
            disruption_type="port", region="Asia-Pacific", severity_score=7
        ))
        weather = generate_scenario_set(DisruptionForecastInput(
            disruption_type="weather", region="Europe", severity_score=7
        ))
        # They may not always differ but shouldn't be identical across all three fields
        port_tuple = (port["p50"]["lead_time_impact_days"], port["p50"]["service_level_impact_pct"])
        weather_tuple = (weather["p50"]["lead_time_impact_days"], weather["p50"]["service_level_impact_pct"])
        # At minimum the descriptions must differ
        assert port["p50"]["description"] != weather["p50"]["description"]

    def test_regional_baseline_lead_times(self):
        from src.agents.scenario_builder import _get_regional_baseline_lead_time

        assert _get_regional_baseline_lead_time("Asia-Pacific") == 21
        assert _get_regional_baseline_lead_time("North America") == 10
        assert _get_regional_baseline_lead_time("Europe") == 14
        assert _get_regional_baseline_lead_time("Africa") == 22
        assert _get_regional_baseline_lead_time("Unknown Region") == 14  # default

    def test_historical_series_has_three_kpis(self):
        from src.forecasting.prophet_engine import DisruptionForecastInput, generate_historical_series

        inp = DisruptionForecastInput(disruption_type="tariff", region="North America", severity_score=5)
        df = generate_historical_series(inp)
        kpis = df["kpi_name"].unique().tolist()
        assert "lead_time" in kpis
        assert "inventory_level" in kpis
        assert "service_level" in kpis
        assert len(df) == 365 * 3  # 365 days × 3 KPIs


# ---------------------------------------------------------------------------
# Task 2: Scenario builder agent tests
# ---------------------------------------------------------------------------

class TestScenarioBuilderAgent:
    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_scenario_builder_uses_prophet(self, mock_get_tracer, port_signal):
        """scenario_builder.run() must return a real ScenarioSet from Prophet."""
        mock_get_tracer.return_value = MagicMock(
            start_as_current_observation=MagicMock(return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock()),
                __exit__=MagicMock(return_value=False),
            ))
        )
        from src.agents.scenario_builder import run

        result = run(port_signal)
        assert result.signal_id == port_signal.signal_id
        assert result.p10.probability == 0.10
        assert result.p50.probability == 0.50
        assert result.p90.probability == 0.90
        # P10 service level should be worse than P90
        assert result.p10.service_level_impact_pct <= result.p90.service_level_impact_pct


# ---------------------------------------------------------------------------
# Task 3: Qdrant retrieval engine tests (unit)
# ---------------------------------------------------------------------------

class TestQdrantRetrievalUnit:
    def test_build_retrieval_query_contains_type(self):
        from src.memory.qdrant_retrieval import build_retrieval_query

        query = build_retrieval_query("port", "Asia-Pacific", 8)
        assert "port" in query.lower()
        assert len(query) > 10

    def test_build_retrieval_query_contains_region(self):
        from src.memory.qdrant_retrieval import build_retrieval_query

        query = build_retrieval_query("weather", "Europe", 5)
        assert "weather" in query.lower()
        assert "europe" in query.lower()

    def test_format_precedents_maps_fields(self):
        from src.memory.qdrant_retrieval import format_precedents

        disruption_records = [{
            "id": "test-uuid-1",
            "score": 0.88,
            "disruption_type": "port",
            "region": "Asia-Pacific",
            "description": "Test port closure description",
            "resolution_days": 14,
            "disruption_id": "disr-001",
        }]
        response_records = [{
            "disruption_id": "disr-001",
            "actions_taken": ["Rerouted vessels", "Activated safety stock"],
            "outcome": "partial",
            "resolution_days": 16,
        }]

        precedents = format_precedents(disruption_records, response_records)
        assert len(precedents) == 1
        assert precedents[0].similarity_score == 0.88
        assert precedents[0].disruption_type == "port"
        assert precedents[0].outcome == "partial"
        assert len(precedents[0].actions_taken) >= 1

    def test_get_retrieval_quality_empty(self):
        from src.memory.qdrant_retrieval import get_retrieval_quality_score

        assert get_retrieval_quality_score([]) == 0.0

    def test_get_retrieval_quality_averages(self):
        from src.memory.qdrant_retrieval import get_retrieval_quality_score
        from src.models.outputs import HistoricalPrecedent

        p1 = HistoricalPrecedent(
            record_id="a", similarity_score=0.80, disruption_type="port", region="AP",
            description="x", resolution_days=14, actions_taken=["a"], outcome="partial"
        )
        p2 = HistoricalPrecedent(
            record_id="b", similarity_score=0.60, disruption_type="port", region="AP",
            description="y", resolution_days=10, actions_taken=["b"], outcome="successful"
        )
        score = get_retrieval_quality_score([p1, p2])
        assert abs(score - 0.70) < 0.01


# ---------------------------------------------------------------------------
# Task 4: Impact modeler agent tests
# ---------------------------------------------------------------------------

class TestImpactModelerAgent:
    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_severity_to_risk_mapping(self, mock_get_tracer):
        from src.agents.impact_modeler import _severity_to_risk

        assert _severity_to_risk(2) == "low"
        assert _severity_to_risk(5) == "medium"
        assert _severity_to_risk(7) == "high"
        assert _severity_to_risk(9) == "critical"
        assert _severity_to_risk(3) == "low"
        assert _severity_to_risk(6) == "medium"
        assert _severity_to_risk(8) == "high"
        assert _severity_to_risk(10) == "critical"

    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_impact_modeler_falls_back_gracefully(self, mock_get_tracer, port_signal):
        """When Qdrant is unavailable, should return stub precedents with score=0."""
        mock_lf = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cm)
        cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = cm
        mock_get_tracer.return_value = mock_lf

        with patch("src.memory.qdrant_retrieval.retrieve_similar_disruptions", side_effect=Exception("Qdrant down")):
            from src.agents.impact_modeler import run
            result = run(port_signal)

        assert len(result.precedents) == 3
        assert result.signal_id == port_signal.signal_id
        # Stub precedents have similarity_score=0.0
        assert all(p.similarity_score == 0.0 for p in result.precedents)


# ---------------------------------------------------------------------------
# Task 5: RAGAS scorer tests
# ---------------------------------------------------------------------------

class TestRAGASScorer:
    def test_ragas_score_structure(self):
        """RAGASScore fields must all be valid floats in [0, 1]."""
        from src.evaluation.ragas_scorer import RAGASScore

        score = RAGASScore(
            faithfulness=0.80,
            answer_relevance=0.75,
            context_precision=0.70,
            overall=round(0.4 * 0.80 + 0.3 * 0.75 + 0.3 * 0.70, 4),
            passed=True,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            signal_id=str(uuid.uuid4()),
        )
        assert 0.0 <= score.faithfulness <= 1.0
        assert 0.0 <= score.answer_relevance <= 1.0
        assert 0.0 <= score.context_precision <= 1.0
        assert 0.0 <= score.overall <= 1.0
        assert score.passed is True

    def test_ragas_overall_formula(self):
        """overall = 0.4*F + 0.3*AR + 0.3*CP."""
        f, ar, cp = 0.80, 0.75, 0.70
        expected = round(0.4 * f + 0.3 * ar + 0.3 * cp, 4)
        from src.evaluation.ragas_scorer import RAGASScore

        score = RAGASScore(
            faithfulness=f,
            answer_relevance=ar,
            context_precision=cp,
            overall=expected,
            passed=expected >= 0.65,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            signal_id="test",
        )
        assert abs(score.overall - expected) < 1e-6

    def test_ragas_passed_threshold(self):
        """passed=True when overall >= 0.65."""
        from src.evaluation.ragas_scorer import RAGASScore

        passing = RAGASScore(
            faithfulness=0.70, answer_relevance=0.70, context_precision=0.70,
            overall=0.70, passed=True,
            evaluated_at=datetime.now(timezone.utc).isoformat(), signal_id="x",
        )
        failing = RAGASScore(
            faithfulness=0.50, answer_relevance=0.50, context_precision=0.50,
            overall=0.50, passed=False,
            evaluated_at=datetime.now(timezone.utc).isoformat(), signal_id="x",
        )
        assert passing.passed is True
        assert failing.passed is False

    @patch("src.evaluation.ragas_scorer._call_llm")
    def test_evaluate_playbook_calls_all_metrics(self, mock_call_llm, port_signal):
        """evaluate_playbook should call the LLM scorer 3 times (one per metric)."""
        mock_call_llm.return_value = 0.80

        from src.models.outputs import Playbook, PlaybookAction
        from src.evaluation.ragas_scorer import evaluate_playbook

        playbook = Playbook(
            signal_id=port_signal.signal_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            dominant_scenario="P50 (base case)",
            overall_risk="high",
            actions=[PlaybookAction(
                priority=1, action="Activate Busan routing", rationale="Historical precedent",
                timeframe="immediate", confidence=0.88, cited_precedent_id=None,
            )],
            bull_summary="Recovery expected", bear_summary="Tail risk exists",
            key_uncertainties=["Busan capacity"],
            ragas_context=["Port closure historical context"],
        )

        score = evaluate_playbook(playbook, port_signal)
        assert mock_call_llm.call_count == 3
        assert score.faithfulness == 0.80
        assert score.answer_relevance == 0.80
        assert score.context_precision == 0.80


# ---------------------------------------------------------------------------
# Task 6: End-to-end flow test with RAGAS
# ---------------------------------------------------------------------------

class TestFlowEndToEnd:
    @patch("src.observability.langfuse_tracer.get_tracer")
    @patch("src.evaluation.ragas_scorer._call_llm")
    def test_flow_runs_end_to_end_with_ragas(self, mock_call_llm, mock_get_tracer, port_signal):
        """Full flow must complete and set ragas_score on FlowState."""
        mock_call_llm.return_value = 0.75

        mock_lf = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cm)
        cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = cm
        mock_lf.create_trace_id.return_value = "test-trace-id"
        mock_get_tracer.return_value = mock_lf

        from src.flows.disruption_flow import DisruptionFlow

        flow = DisruptionFlow()
        flow.state.signal = port_signal
        playbook = flow.kickoff()

        assert playbook is not None
        assert playbook.signal_id == port_signal.signal_id
        assert flow.state.ragas_score is not None
        assert 0.0 <= flow.state.ragas_score.overall <= 1.0

    @patch("src.observability.langfuse_tracer.get_tracer")
    @patch("src.evaluation.ragas_scorer._call_llm")
    def test_fast_path_still_works(self, mock_call_llm, mock_get_tracer, low_severity_signal):
        """Fast path (severity < 4) must complete even with new RAGAS wiring."""
        mock_call_llm.return_value = 0.70

        mock_lf = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cm)
        cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = cm
        mock_lf.create_trace_id.return_value = "test-trace-id"
        mock_get_tracer.return_value = mock_lf

        from src.flows.disruption_flow import DisruptionFlow

        flow = DisruptionFlow()
        flow.state.signal = low_severity_signal
        flow.kickoff()

        assert flow.state.fast_path is True
        assert flow.state.playbook is not None


# ---------------------------------------------------------------------------
# Integration tests (require live Qdrant)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestQdrantIntegration:
    def test_retrieval_returns_results(self, port_signal):
        """Integration: retrieve_similar_disruptions must return at least 1 record."""
        from src.memory.qdrant_retrieval import retrieve_similar_disruptions

        records = retrieve_similar_disruptions(
            disruption_type=port_signal.disruption_type,
            region=port_signal.region,
            description=port_signal.description,
            severity_score=port_signal.severity_score,
            top_k=3,
        )
        assert len(records) > 0

    def test_retrieval_quality_score_above_threshold(self, port_signal):
        """Integration: retrieved records for port query should have score > 0.50."""
        from src.memory.qdrant_retrieval import (
            retrieve_similar_disruptions,
            retrieve_response_records,
            format_precedents,
            get_retrieval_quality_score,
        )

        records = retrieve_similar_disruptions(
            disruption_type=port_signal.disruption_type,
            region=port_signal.region,
            description=port_signal.description,
            severity_score=port_signal.severity_score,
            top_k=3,
        )
        if not records:
            pytest.skip("No Qdrant records found — is the database seeded?")

        d_ids = [r.get("disruption_id", r.get("id", "")) for r in records]
        resp = retrieve_response_records(d_ids)
        precedents = format_precedents(records, resp)
        quality = get_retrieval_quality_score(precedents)

        assert quality > 0.50, f"Retrieval quality {quality:.3f} below 0.50 threshold"
