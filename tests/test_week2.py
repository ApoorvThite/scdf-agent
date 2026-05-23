"""
Week 2 test suite — Pydantic models, FlowState, routing logic, agent imports.

All LLM calls are avoided: stub agent run() functions are called directly
and the Flow is tested with mocked Langfuse so no network calls are made.
"""

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
    SignalAnalysis,
)
from src.signals.mock_generator import DisruptionSignal, generate_mock_signal


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_signal() -> DisruptionSignal:
    return DisruptionSignal(
        signal_id=str(uuid.uuid4()),
        disruption_type="port",
        region="Asia-Pacific",
        severity_score=7,
        description="Port of Shanghai crane operator strike",
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
        description="Minor fog delay at Rotterdam",
        affected_routes=["Europe Intra-Regional"],
        source="Met Office",
    )


@pytest.fixture
def high_severity_signal() -> DisruptionSignal:
    return DisruptionSignal(
        signal_id=str(uuid.uuid4()),
        disruption_type="geopolitical",
        region="Middle East",
        severity_score=9,
        description="Strait of Hormuz tension escalates",
        affected_routes=["Asia-Europe Westbound", "Suez Canal"],
        source="UKMTO Maritime Security",
    )


# ── Model validation tests ─────────────────────────────────────────────────────

class TestSignalAnalysis:
    def test_valid_construction(self, sample_signal):
        analysis = SignalAnalysis(
            signal_id=sample_signal.signal_id,
            disruption_type="port",
            region="Asia-Pacific",
            severity_score=7,
            severity_label="high",
            affected_kpis=["lead_time", "inventory"],
            summary="Port closure in Asia-Pacific.",
            requires_full_crew=True,
        )
        assert analysis.signal_id == sample_signal.signal_id
        assert analysis.severity_score == 7
        assert analysis.requires_full_crew is True

    def test_severity_bounds(self):
        with pytest.raises(Exception):
            SignalAnalysis(
                signal_id="x",
                disruption_type="port",
                region="Asia-Pacific",
                severity_score=11,  # out of range
                severity_label="critical",
                affected_kpis=[],
                summary="test",
                requires_full_crew=True,
            )

    def test_requires_full_crew_false_for_low_severity(self, low_severity_signal):
        analysis = SignalAnalysis(
            signal_id=low_severity_signal.signal_id,
            disruption_type="weather",
            region="Europe",
            severity_score=2,
            severity_label="low",
            affected_kpis=["lead_time"],
            summary="Minor fog delay.",
            requires_full_crew=False,
        )
        assert analysis.requires_full_crew is False


class TestScenarioSet:
    def test_valid_construction(self, sample_signal):
        scenario_set = ScenarioSet(
            signal_id=sample_signal.signal_id,
            p10=Scenario(
                label="P10 (worst case)",
                probability=0.10,
                description="Worst case",
                inventory_impact_pct=-35.0,
                lead_time_impact_days=42,
                service_level_impact_pct=-28.0,
                resolution_days_estimate=56,
            ),
            p50=Scenario(
                label="P50 (base case)",
                probability=0.50,
                description="Base case",
                inventory_impact_pct=-15.0,
                lead_time_impact_days=18,
                service_level_impact_pct=-12.0,
                resolution_days_estimate=28,
            ),
            p90=Scenario(
                label="P90 (best case)",
                probability=0.90,
                description="Best case",
                inventory_impact_pct=-5.0,
                lead_time_impact_days=7,
                service_level_impact_pct=-4.0,
                resolution_days_estimate=14,
            ),
            forecast_confidence=0.72,
            data_quality_note="Based on 60 historical records.",
        )
        assert scenario_set.p10.probability == 0.10
        assert scenario_set.p90.resolution_days_estimate == 14


class TestImpactAnalysis:
    def test_valid_construction(self, sample_signal):
        precedent = HistoricalPrecedent(
            record_id=str(uuid.uuid4()),
            similarity_score=0.88,
            disruption_type="port",
            region="Asia-Pacific",
            description="Historical port closure",
            resolution_days=21,
            actions_taken=["Activated Busan routing"],
            outcome="partial",
        )
        analysis = ImpactAnalysis(
            signal_id=sample_signal.signal_id,
            precedents=[precedent],
            kpi_impacts={"lead_time": "+14 days"},
            risk_level="high",
            retrieval_quality=0.88,
        )
        assert len(analysis.precedents) == 1
        assert analysis.precedents[0].similarity_score == 0.88


class TestAnalystPosition:
    def test_bull_position(self, sample_signal):
        pos = AnalystPosition(
            position="bull",
            signal_id=sample_signal.signal_id,
            thesis="Recovery will be fast.",
            key_evidence=["Evidence A", "Evidence B"],
            recommended_scenario="P90 (best case)",
            confidence=0.75,
            dissenting_risk="Secondary port congestion",
        )
        assert pos.position == "bull"
        assert pos.confidence == 0.75

    def test_bear_position(self, sample_signal):
        pos = AnalystPosition(
            position="bear",
            signal_id=sample_signal.signal_id,
            thesis="Escalation risk is high.",
            key_evidence=["Risk A", "Risk B"],
            recommended_scenario="P10 (worst case)",
            confidence=0.68,
            dissenting_risk="Early resolution",
        )
        assert pos.position == "bear"


class TestPlaybook:
    def test_valid_construction(self, sample_signal):
        action = PlaybookAction(
            priority=1,
            action="Activate Busan routing",
            rationale="Historical precedent shows effectiveness",
            timeframe="immediate",
            confidence=0.88,
            cited_precedent_id=str(uuid.uuid4()),
        )
        playbook = Playbook(
            signal_id=sample_signal.signal_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            dominant_scenario="P50 (base case)",
            overall_risk="high",
            actions=[action],
            bull_summary="Fast recovery expected",
            bear_summary="Tail risk of 6-week disruption",
            key_uncertainties=["Busan capacity trajectory"],
            ragas_context=["Historical context text"],
        )
        assert len(playbook.actions) == 1
        assert playbook.actions[0].priority == 1
        assert playbook.actions[0].cited_precedent_id is not None

    def test_action_without_precedent(self, sample_signal):
        action = PlaybookAction(
            priority=1,
            action="Issue customer comms",
            rationale="Transparency reduces penalties",
            timeframe="72h",
            confidence=0.91,
            cited_precedent_id=None,
        )
        assert action.cited_precedent_id is None


# ── FlowState tests ────────────────────────────────────────────────────────────

class TestFlowState:
    def test_initialises_without_signal(self):
        from src.flows.disruption_flow import FlowState
        state = FlowState()
        assert state.signal is None
        assert state.fast_path is False
        assert state.completed_at is None
        assert state.run_id is not None

    def test_initialises_with_signal(self, sample_signal):
        from src.flows.disruption_flow import FlowState
        state = FlowState(signal=sample_signal)
        assert state.signal.signal_id == sample_signal.signal_id

    def test_run_id_is_generated(self):
        from src.flows.disruption_flow import FlowState
        s1 = FlowState()
        s2 = FlowState()
        assert s1.run_id != s2.run_id


# ── Agent stub run() tests ─────────────────────────────────────────────────────

class TestStubAgents:
    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_signal_ingester_high_severity(self, mock_get_tracer, high_severity_signal):
        mock_lf = MagicMock()
        mock_get_tracer.return_value = mock_lf
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm

        from src.agents.signal_ingester import run
        result = run(high_severity_signal)
        assert result.requires_full_crew is True
        assert result.severity_score == 9
        assert result.signal_id == high_severity_signal.signal_id

    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_signal_ingester_low_severity(self, mock_get_tracer, low_severity_signal):
        mock_lf = MagicMock()
        mock_get_tracer.return_value = mock_lf
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm

        from src.agents.signal_ingester import run
        result = run(low_severity_signal)
        assert result.requires_full_crew is False
        assert result.severity_label == "low"

    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_scenario_builder_returns_all_scenarios(self, mock_get_tracer, sample_signal):
        mock_lf = MagicMock()
        mock_get_tracer.return_value = mock_lf
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm

        from src.agents.scenario_builder import run
        result = run(sample_signal)
        assert result.p10.probability == 0.10
        assert result.p50.probability == 0.50
        assert result.p90.probability == 0.90

    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_impact_modeler_returns_three_precedents(self, mock_get_tracer, sample_signal):
        mock_lf = MagicMock()
        mock_get_tracer.return_value = mock_lf
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm

        from src.agents.impact_modeler import run
        result = run(sample_signal)
        assert len(result.precedents) == 3
        assert all(0 < p.similarity_score <= 1.0 for p in result.precedents)

    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_bull_analyst_returns_bull_position(self, mock_get_tracer, sample_signal):
        mock_lf = MagicMock()
        mock_get_tracer.return_value = mock_lf
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm

        from src.agents.bull_analyst import run
        result = run(sample_signal)
        assert result.position == "bull"
        assert len(result.key_evidence) >= 3

    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_bear_analyst_returns_bear_position(self, mock_get_tracer, sample_signal):
        mock_lf = MagicMock()
        mock_get_tracer.return_value = mock_lf
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm

        from src.agents.bear_analyst import run
        result = run(sample_signal)
        assert result.position == "bear"

    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_playbook_writer_returns_playbook(self, mock_get_tracer, sample_signal):
        mock_lf = MagicMock()
        mock_get_tracer.return_value = mock_lf
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm

        from src.agents.playbook_writer import run
        result = run(sample_signal)
        assert len(result.actions) >= 1
        assert result.actions[0].priority == 1


# ── Flow routing tests ─────────────────────────────────────────────────────────

class TestFlowRouting:
    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_full_debate_path_high_severity(self, mock_get_tracer, high_severity_signal):
        """High severity (>=7) must trigger full debate path."""
        mock_lf = MagicMock()
        mock_get_tracer.return_value = mock_lf
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm

        from src.flows.disruption_flow import DisruptionFlow
        flow = DisruptionFlow()
        flow.state.signal = high_severity_signal
        flow.kickoff()

        assert flow.state.signal_analysis.requires_full_crew is True
        assert flow.state.fast_path is False
        assert flow.state.bull_position is not None
        assert flow.state.bear_position is not None

    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_fast_path_low_severity(self, mock_get_tracer, low_severity_signal):
        """Low severity (<4) must trigger fast path (no debate)."""
        mock_lf = MagicMock()
        mock_get_tracer.return_value = mock_lf
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm

        from src.flows.disruption_flow import DisruptionFlow
        flow = DisruptionFlow()
        flow.state.signal = low_severity_signal
        flow.kickoff()

        assert flow.state.fast_path is True
        assert flow.state.bull_position is None
        assert flow.state.bear_position is None

    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_flow_completes_without_exception(self, mock_get_tracer, sample_signal):
        """Full flow run must complete without raising exceptions."""
        mock_lf = MagicMock()
        mock_get_tracer.return_value = mock_lf
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm

        from src.flows.disruption_flow import run
        playbook = run(sample_signal)
        assert playbook is not None
        assert playbook.signal_id == sample_signal.signal_id

    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_playbook_has_actions(self, mock_get_tracer, sample_signal):
        mock_lf = MagicMock()
        mock_get_tracer.return_value = mock_lf
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm

        from src.flows.disruption_flow import run
        playbook = run(sample_signal)
        assert len(playbook.actions) >= 1
        priorities = [a.priority for a in playbook.actions]
        assert 1 in priorities


# ── Import smoke tests ─────────────────────────────────────────────────────────

class TestImports:
    def test_all_agents_import_cleanly(self):
        """Verify no circular imports or module-level errors in agent files."""
        import src.agents.signal_ingester  # noqa
        import src.agents.scenario_builder  # noqa
        import src.agents.impact_modeler  # noqa
        import src.agents.bull_analyst  # noqa
        import src.agents.bear_analyst  # noqa
        import src.agents.playbook_writer  # noqa

    def test_agents_init_exports(self):
        from src.agents import (
            signal_ingester_agent,
            scenario_builder_agent,
            impact_modeler_agent,
            bull_analyst_agent,
            bear_analyst_agent,
            playbook_writer_agent,
        )
        for agent_obj in [
            signal_ingester_agent,
            scenario_builder_agent,
            impact_modeler_agent,
            bull_analyst_agent,
            bear_analyst_agent,
            playbook_writer_agent,
        ]:
            assert hasattr(agent_obj, "role")
            assert hasattr(agent_obj, "goal")

    def test_flow_imports_cleanly(self):
        from src.flows.disruption_flow import DisruptionFlow, FlowState, run  # noqa
        assert DisruptionFlow is not None

    def test_models_import_cleanly(self):
        from src.models import (
            SignalAnalysis, Scenario, ScenarioSet,
            HistoricalPrecedent, ImpactAnalysis,
            AnalystPosition, PlaybookAction, Playbook,
        )  # noqa
        assert Playbook is not None
