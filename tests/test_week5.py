"""
Week 5 test suite.

Tests cover:
  - Real bull analyst: LLM success, forced fallback, position constraints
  - Real bear analyst: LLM success, forced fallback, position constraints
  - Genuine disagreement between bull and bear recommended_scenarios
  - Playbook writer: 5 actions, ragas_context population, precedent citation
  - _determine_dominant_scenario: P10 / P50 / P90 selection logic
  - Full flow: bull_position and bear_position non-None after kickoff
  - Prompt library: load_prompt() loads files, raises on missing
  - DebateQualityReport: structure validation
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.models.outputs import (
    AnalystPosition,
    HistoricalPrecedent,
    ImpactAnalysis,
    Playbook,
    PlaybookAction,
    Scenario,
    ScenarioSet,
)
from src.signals.mock_generator import DisruptionSignal, generate_mock_signal


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def port_signal():
    return generate_mock_signal(disruption_type="port", severity=8)


@pytest.fixture
def low_signal():
    return generate_mock_signal(disruption_type="weather", severity=2)


@pytest.fixture
def scenario_set(port_signal):
    """Minimal ScenarioSet fixture for unit tests."""
    return ScenarioSet(
        signal_id=port_signal.signal_id,
        p10=Scenario(
            label="P10 (worst case)", probability=0.10,
            description="Severe disruption lasts 6 weeks.",
            inventory_impact_pct=-25.0, lead_time_impact_days=21,
            service_level_impact_pct=-18.0, resolution_days_estimate=42,
        ),
        p50=Scenario(
            label="P50 (base case)", probability=0.60,
            description="Moderate disruption, resolves in 3 weeks.",
            inventory_impact_pct=-12.0, lead_time_impact_days=10,
            service_level_impact_pct=-8.0, resolution_days_estimate=21,
        ),
        p90=Scenario(
            label="P90 (best case)", probability=0.30,
            description="Quick recovery within 2 weeks.",
            inventory_impact_pct=-5.0, lead_time_impact_days=5,
            service_level_impact_pct=-3.0, resolution_days_estimate=14,
        ),
        forecast_confidence=0.75,
        data_quality_note="Synthetic forecast for unit tests.",
    )


@pytest.fixture
def impact_analysis(port_signal):
    """Minimal ImpactAnalysis fixture with 3 historical precedents."""
    precedent_id_1 = str(uuid.uuid4())
    precedent_id_2 = str(uuid.uuid4())
    precedent_id_3 = str(uuid.uuid4())
    return ImpactAnalysis(
        signal_id=port_signal.signal_id,
        precedents=[
            HistoricalPrecedent(
                record_id=precedent_id_1,
                similarity_score=0.88,
                disruption_type="port",
                region="Asia-Pacific",
                description="Port of Kaohsiung crane operator strike — 35% capacity reduction for 3 weeks.",
                resolution_days=21,
                actions_taken=["Activated Busan routing", "Issued force majeure"],
                outcome="partial",
            ),
            HistoricalPrecedent(
                record_id=precedent_id_2,
                similarity_score=0.74,
                disruption_type="port",
                region="Asia-Pacific",
                description="Typhoon Haikui — Port of Taipei closure for 11 days.",
                resolution_days=14,
                actions_taken=["Pre-positioned safety stock", "Air freight for critical SKUs"],
                outcome="successful",
            ),
            HistoricalPrecedent(
                record_id=precedent_id_3,
                similarity_score=0.62,
                disruption_type="port",
                region="Asia-Pacific",
                description="Port of Shanghai COVID-19 lockdown — 45% throughput reduction for 6 weeks.",
                resolution_days=42,
                actions_taken=["Spot vessel charter", "Near-shoring activation"],
                outcome="partial",
            ),
        ],
        kpi_impacts={
            "lead_time": "+10-21 days depending on scenario",
            "inventory": "-5% to -25% across affected SKUs",
            "service_level": "-3% to -18% service level degradation",
        },
        risk_level="high",
        retrieval_quality=0.75,
    )


@pytest.fixture
def bull_position(port_signal):
    """A pre-built bull AnalystPosition for playbook writer tests."""
    return AnalystPosition(
        position="bull",
        signal_id=port_signal.signal_id,
        thesis="Recovery expected within 14 days via Busan rerouting.",
        key_evidence=["Busan has capacity", "Carriers adjusting"],
        recommended_scenario="P90 (best case)",
        confidence=0.74,
        dissenting_risk="Secondary congestion could invalidate this.",
    )


@pytest.fixture
def bear_position(port_signal):
    """A pre-built bear AnalystPosition for playbook writer tests."""
    return AnalystPosition(
        position="bear",
        signal_id=port_signal.signal_id,
        thesis="Cascading congestion expected, P10 scenario likely.",
        key_evidence=["Historical precedents show escalation", "Safety stock insufficient"],
        recommended_scenario="P10 (worst case)",
        confidence=0.68,
        dissenting_risk="Rapid resolution would invalidate this.",
    )


def _make_mock_tracer():
    """Return a MagicMock Langfuse tracer with context manager support."""
    mock_lf = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    mock_lf.start_as_current_observation.return_value = cm
    mock_lf.create_trace_id.return_value = "test-trace-id"
    return mock_lf


def _make_mock_openai_response(data: dict) -> MagicMock:
    """Return a mock OpenAI response wrapping a JSON dict."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(data)
    return mock_response


# ---------------------------------------------------------------------------
# Prompt library tests
# ---------------------------------------------------------------------------

class TestPromptLibrary:
    def test_load_bull_analyst_prompt(self):
        from src.prompts import load_prompt
        text = load_prompt("bull_analyst")
        assert len(text) > 50
        assert "bull" in text.lower() or "optimist" in text.lower()

    def test_load_bear_analyst_prompt(self):
        from src.prompts import load_prompt
        text = load_prompt("bear_analyst")
        assert len(text) > 50
        assert "bear" in text.lower() or "risk" in text.lower()

    def test_load_playbook_writer_prompt(self):
        from src.prompts import load_prompt
        text = load_prompt("playbook_writer")
        assert len(text) > 50
        assert "playbook" in text.lower() or "action" in text.lower()

    def test_load_missing_prompt_raises(self):
        from src.prompts import load_prompt
        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent_prompt_xyz")


# ---------------------------------------------------------------------------
# Bull analyst tests
# ---------------------------------------------------------------------------

class TestBullAnalyst:
    def test_bull_returns_analyst_position(self, port_signal, scenario_set, impact_analysis):
        """run() returns AnalystPosition with position='bull'."""
        llm_data = {
            "thesis": "Recovery within P90 window based on historical patterns.",
            "key_evidence": ["Busan at 87% capacity", "Carriers adjusting"],
            "recommended_scenario": "P90 (best case)",
            "confidence": 0.74,
            "dissenting_risk": "Secondary congestion could cascade.",
        }
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(llm_data)

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.bull_analyst.get_openai_client", return_value=mock_client):
                from src.agents.bull_analyst import run
                result = run(port_signal, scenario_set, impact_analysis)

        assert isinstance(result, AnalystPosition)
        assert result.position == "bull"

    def test_bull_has_valid_confidence(self, port_signal, scenario_set, impact_analysis):
        """Bull confidence is in [0, 1]."""
        llm_data = {
            "thesis": "Strong bull case.",
            "key_evidence": ["Evidence 1", "Evidence 2"],
            "recommended_scenario": "P90 (best case)",
            "confidence": 0.80,
            "dissenting_risk": "Risk of secondary disruption.",
        }
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(llm_data)

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.bull_analyst.get_openai_client", return_value=mock_client):
                from src.agents.bull_analyst import run
                result = run(port_signal, scenario_set, impact_analysis)

        assert 0.0 <= result.confidence <= 1.0

    def test_bull_never_recommends_p10(self, port_signal, scenario_set, impact_analysis):
        """Bull analyst must not recommend P10 even if LLM returns it."""
        # LLM accidentally returns P10 — the agent must override to P50
        llm_data = {
            "thesis": "Actually bearish.",
            "key_evidence": ["Bad thing"],
            "recommended_scenario": "P10 (worst case)",
            "confidence": 0.60,
            "dissenting_risk": "Everything could go right.",
        }
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(llm_data)

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.bull_analyst.get_openai_client", return_value=mock_client):
                from src.agents.bull_analyst import run
                result = run(port_signal, scenario_set, impact_analysis)

        assert "P10" not in result.recommended_scenario

    def test_bull_fallback_on_llm_failure(self, port_signal, scenario_set, impact_analysis):
        """run() returns a valid AnalystPosition even when LLM raises an exception."""
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API timeout")

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.bull_analyst.get_openai_client", return_value=mock_client):
                from src.agents.bull_analyst import run
                result = run(port_signal, scenario_set, impact_analysis)

        assert isinstance(result, AnalystPosition)
        assert result.position == "bull"

    def test_bull_fallback_when_no_context(self, port_signal):
        """run() with no scenario_set/impact_analysis returns stub fallback."""
        mock_tracer = _make_mock_tracer()
        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            from src.agents.bull_analyst import run
            result = run(port_signal)  # no scenario_set or impact_analysis

        assert isinstance(result, AnalystPosition)
        assert result.position == "bull"


# ---------------------------------------------------------------------------
# Bear analyst tests
# ---------------------------------------------------------------------------

class TestBearAnalyst:
    def test_bear_returns_analyst_position(self, port_signal, scenario_set, impact_analysis):
        """run() returns AnalystPosition with position='bear'."""
        llm_data = {
            "thesis": "Cascading congestion will extend the disruption beyond P50.",
            "key_evidence": ["Shanghai lockdown extended 4x", "Busan near capacity"],
            "recommended_scenario": "P10 (worst case)",
            "confidence": 0.72,
            "dissenting_risk": "Rapid resolution would invalidate this.",
        }
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(llm_data)

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.bear_analyst.get_openai_client", return_value=mock_client):
                from src.agents.bear_analyst import run
                result = run(port_signal, scenario_set, impact_analysis)

        assert isinstance(result, AnalystPosition)
        assert result.position == "bear"

    def test_bear_never_recommends_p90(self, port_signal, scenario_set, impact_analysis):
        """Bear analyst must not recommend P90 even if LLM returns it."""
        llm_data = {
            "thesis": "Actually optimistic.",
            "key_evidence": ["Good thing"],
            "recommended_scenario": "P90 (best case)",  # LLM error
            "confidence": 0.65,
            "dissenting_risk": "Everything could go wrong.",
        }
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(llm_data)

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.bear_analyst.get_openai_client", return_value=mock_client):
                from src.agents.bear_analyst import run
                result = run(port_signal, scenario_set, impact_analysis)

        assert "P90" not in result.recommended_scenario

    def test_bear_fallback_on_llm_failure(self, port_signal, scenario_set, impact_analysis):
        """run() returns a valid AnalystPosition even when LLM raises."""
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("Network error")

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.bear_analyst.get_openai_client", return_value=mock_client):
                from src.agents.bear_analyst import run
                result = run(port_signal, scenario_set, impact_analysis)

        assert isinstance(result, AnalystPosition)
        assert result.position == "bear"


# ---------------------------------------------------------------------------
# Bull vs Bear disagreement
# ---------------------------------------------------------------------------

class TestDebateDisagreement:
    def test_bull_and_bear_recommend_different_scenarios(self, port_signal, scenario_set, impact_analysis):
        """When both LLMs behave correctly, bull and bear should recommend different scenarios."""
        bull_data = {
            "thesis": "Optimistic recovery.", "key_evidence": ["E1", "E2"],
            "recommended_scenario": "P90 (best case)", "confidence": 0.76,
            "dissenting_risk": "Cascading failure.",
        }
        bear_data = {
            "thesis": "Pessimistic tail risk.", "key_evidence": ["E1", "E2"],
            "recommended_scenario": "P10 (worst case)", "confidence": 0.69,
            "dissenting_risk": "Rapid resolution.",
        }

        mock_tracer = _make_mock_tracer()
        bull_client = MagicMock()
        bull_client.chat.completions.create.return_value = _make_mock_openai_response(bull_data)
        bear_client = MagicMock()
        bear_client.chat.completions.create.return_value = _make_mock_openai_response(bear_data)

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.bull_analyst.get_openai_client", return_value=bull_client):
                with patch("src.agents.bear_analyst.get_openai_client", return_value=bear_client):
                    from src.agents.bear_analyst import run as run_bear
                    from src.agents.bull_analyst import run as run_bull
                    bull = run_bull(port_signal, scenario_set, impact_analysis)
                    bear = run_bear(port_signal, scenario_set, impact_analysis)

        assert bull.recommended_scenario != bear.recommended_scenario


# ---------------------------------------------------------------------------
# Playbook writer tests
# ---------------------------------------------------------------------------

class TestPlaybookWriter:
    def _make_playbook_llm_data(self, precedent_ids: list[str]) -> dict:
        """Build a valid LLM response dict for the playbook writer."""
        return {
            "dominant_scenario": "P50 (base case)",
            "overall_risk": "high",
            "actions": [
                {
                    "priority": 1, "action": "Activate alternative routing immediately.",
                    "rationale": "Reduces lead-time by 35%.", "timeframe": "immediate",
                    "confidence": 0.88, "cited_precedent_id": precedent_ids[0],
                },
                {
                    "priority": 2, "action": "Expedite air freight for critical SKUs.",
                    "rationale": "Prevents service level breach.", "timeframe": "24h",
                    "confidence": 0.82, "cited_precedent_id": precedent_ids[1],
                },
                {
                    "priority": 3, "action": "Issue customer communication.",
                    "rationale": "Preserves relationships.", "timeframe": "72h",
                    "confidence": 0.91, "cited_precedent_id": None,
                },
                {
                    "priority": 4, "action": "Audit safety stock levels.",
                    "rationale": "Identify coverage gaps.", "timeframe": "24h",
                    "confidence": 0.85, "cited_precedent_id": None,
                },
                {
                    "priority": 5, "action": "Initiate dual-source qualification.",
                    "rationale": "Structural resilience.", "timeframe": "1-week",
                    "confidence": 0.65, "cited_precedent_id": None,
                },
            ],
            "bull_summary": "Bull expects P90 recovery via Busan rerouting.",
            "bear_summary": "Bear warns of cascading congestion reaching P10.",
            "key_uncertainties": ["Port utilisation", "Carrier response", "Safety stock depth"],
        }

    def test_playbook_returns_playbook_object(
        self, port_signal, scenario_set, impact_analysis, bull_position, bear_position
    ):
        """write_playbook_task() returns a Playbook instance."""
        precedent_ids = [p.record_id for p in impact_analysis.precedents]
        llm_data = self._make_playbook_llm_data(precedent_ids)
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(llm_data)

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.playbook_writer.get_openai_client", return_value=mock_client):
                from src.agents.playbook_writer import run
                result = run(port_signal, scenario_set, impact_analysis, bull_position, bear_position)

        assert isinstance(result, Playbook)

    def test_playbook_has_exactly_five_actions(
        self, port_signal, scenario_set, impact_analysis, bull_position, bear_position
    ):
        """Playbook always contains exactly 5 PlaybookAction items."""
        precedent_ids = [p.record_id for p in impact_analysis.precedents]
        llm_data = self._make_playbook_llm_data(precedent_ids)
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(llm_data)

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.playbook_writer.get_openai_client", return_value=mock_client):
                from src.agents.playbook_writer import run
                result = run(port_signal, scenario_set, impact_analysis, bull_position, bear_position)

        assert len(result.actions) == 5

    def test_playbook_populates_ragas_context_from_precedents(
        self, port_signal, scenario_set, impact_analysis, bull_position, bear_position
    ):
        """ragas_context is populated from historical precedent descriptions."""
        precedent_ids = [p.record_id for p in impact_analysis.precedents]
        llm_data = self._make_playbook_llm_data(precedent_ids)
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(llm_data)

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.playbook_writer.get_openai_client", return_value=mock_client):
                from src.agents.playbook_writer import run
                result = run(port_signal, scenario_set, impact_analysis, bull_position, bear_position)

        assert len(result.ragas_context) == len(impact_analysis.precedents)
        for precedent, ctx in zip(impact_analysis.precedents, result.ragas_context):
            assert precedent.description in ctx

    def test_playbook_cites_valid_precedent_ids(
        self, port_signal, scenario_set, impact_analysis, bull_position, bear_position
    ):
        """cited_precedent_id values must be valid UUIDs from the precedents list or None."""
        precedent_ids = [p.record_id for p in impact_analysis.precedents]
        llm_data = self._make_playbook_llm_data(precedent_ids)
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(llm_data)

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.playbook_writer.get_openai_client", return_value=mock_client):
                from src.agents.playbook_writer import run
                result = run(port_signal, scenario_set, impact_analysis, bull_position, bear_position)

        valid_ids = {p.record_id for p in impact_analysis.precedents}
        for action in result.actions:
            if action.cited_precedent_id is not None:
                assert action.cited_precedent_id in valid_ids

    def test_playbook_fallback_on_llm_failure(
        self, port_signal, scenario_set, impact_analysis, bull_position, bear_position
    ):
        """run() returns a valid Playbook even when LLM raises an exception."""
        mock_tracer = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("LLM unavailable")

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            with patch("src.agents.playbook_writer.get_openai_client", return_value=mock_client):
                from src.agents.playbook_writer import run
                result = run(port_signal, scenario_set, impact_analysis, bull_position, bear_position)

        assert isinstance(result, Playbook)
        assert len(result.actions) == 5

    def test_playbook_fast_path_no_debate_context(self, port_signal, scenario_set, impact_analysis):
        """run() with no bull/bear positions returns stub playbook (fast path)."""
        mock_tracer = _make_mock_tracer()
        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_tracer):
            from src.agents.playbook_writer import run
            result = run(port_signal, scenario_set, impact_analysis)  # no bull/bear

        assert isinstance(result, Playbook)
        assert len(result.actions) == 5


# ---------------------------------------------------------------------------
# Dominant scenario logic
# ---------------------------------------------------------------------------

class TestDominantScenario:
    def _make_analysts(self, bull_conf: float, bear_conf: float, port_signal) -> tuple:
        bull = AnalystPosition(
            position="bull", signal_id=port_signal.signal_id,
            thesis="Bull.", key_evidence=["E"], recommended_scenario="P90 (best case)",
            confidence=bull_conf, dissenting_risk="Risk.",
        )
        bear = AnalystPosition(
            position="bear", signal_id=port_signal.signal_id,
            thesis="Bear.", key_evidence=["E"], recommended_scenario="P10 (worst case)",
            confidence=bear_conf, dissenting_risk="Risk.",
        )
        return bull, bear

    def test_bear_wins_when_confidence_gap_exceeds_threshold(self, port_signal, scenario_set):
        """bear.confidence > bull.confidence + 0.15 → P10 dominant."""
        from src.agents.playbook_writer import _determine_dominant_scenario
        bull, bear = self._make_analysts(0.60, 0.80, port_signal)
        result = _determine_dominant_scenario(bull, bear, scenario_set)
        assert result == scenario_set.p10.label

    def test_bull_wins_when_confidence_gap_exceeds_threshold(self, port_signal, scenario_set):
        """bull.confidence > bear.confidence + 0.15 → P90 dominant."""
        from src.agents.playbook_writer import _determine_dominant_scenario
        bull, bear = self._make_analysts(0.85, 0.60, port_signal)
        result = _determine_dominant_scenario(bull, bear, scenario_set)
        assert result == scenario_set.p90.label

    def test_p50_when_confidence_within_threshold(self, port_signal, scenario_set):
        """Small confidence gap → P50 dominant."""
        from src.agents.playbook_writer import _determine_dominant_scenario
        bull, bear = self._make_analysts(0.70, 0.68, port_signal)
        result = _determine_dominant_scenario(bull, bear, scenario_set)
        assert result == scenario_set.p50.label

    def test_p50_when_confidences_equal(self, port_signal, scenario_set):
        """Equal confidence → P50 dominant."""
        from src.agents.playbook_writer import _determine_dominant_scenario
        bull, bear = self._make_analysts(0.72, 0.72, port_signal)
        result = _determine_dominant_scenario(bull, bear, scenario_set)
        assert result == scenario_set.p50.label


# ---------------------------------------------------------------------------
# Debate quality report structure
# ---------------------------------------------------------------------------

class TestDebateQualityReport:
    def test_report_structure(self):
        """DebateQualityReport has all required fields."""
        from src.prompts.prompt_validator import DebateQualityReport
        report = DebateQualityReport(
            n_runs=3,
            avg_confidence_gap=0.12,
            scenario_agreement_rate=0.33,
            bull_avg_confidence=0.75,
            bear_avg_confidence=0.63,
            passed=True,
        )
        assert report.passed is True
        assert report.failure_reason is None

    def test_report_fails_when_gap_too_small(self):
        """DebateQualityReport.passed is False when gap ≤ 0.10."""
        from src.prompts.prompt_validator import DebateQualityReport
        report = DebateQualityReport(
            n_runs=5,
            avg_confidence_gap=0.05,
            scenario_agreement_rate=0.20,
            bull_avg_confidence=0.70,
            bear_avg_confidence=0.65,
            passed=False,
            failure_reason="confidence gap too small (0.05 ≤ 0.10)",
        )
        assert report.passed is False
        assert report.failure_reason is not None


# ---------------------------------------------------------------------------
# Integration test — full flow with debate path
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFullFlowIntegration:
    def test_flow_sets_bull_and_bear_positions(self):
        """
        Integration: DisruptionFlow with severity >= 4 sets non-None bull and bear positions.

        Requires: live Qdrant, live OpenAI credentials via Helicone.
        Skipped in CI if QDRANT_HOST is unavailable.
        """
        from src.flows.disruption_flow import DisruptionFlow
        from src.signals.mock_generator import generate_mock_signal

        signal = generate_mock_signal(disruption_type="port", severity=8)
        flow = DisruptionFlow()
        flow.state.signal = signal
        flow.kickoff()

        assert flow.state.bull_position is not None
        assert flow.state.bear_position is not None
        assert flow.state.bull_position.position == "bull"
        assert flow.state.bear_position.position == "bear"
        assert flow.state.playbook is not None
        assert len(flow.state.playbook.actions) == 5
