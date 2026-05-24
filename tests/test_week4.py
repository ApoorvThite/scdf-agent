"""
Week 4 test suite.

Tests cover:
  - Real signal ingester LLM call + rule-based fallback
  - Severity label / requires_full_crew logic
  - DynamoDB float→Decimal conversion + save/retrieve (mocked)
  - SNS dev-mode no-publish behaviour
  - Lambda handler 200 / 500 responses
  - Redis publish + consume round-trip (integration, skipped if Redis unavailable)
"""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

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
def tariff_signal():
    return generate_mock_signal(disruption_type="tariff", severity=5)


def _make_mock_tracer():
    """Return a MagicMock Langfuse tracer with context manager support."""
    mock_lf = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    mock_lf.start_as_current_observation.return_value = cm
    mock_lf.create_trace_id.return_value = "test-trace-id"
    return mock_lf


# ---------------------------------------------------------------------------
# Task 1 — Signal Ingester
# ---------------------------------------------------------------------------

class TestSignalIngester:
    @patch("src.observability.langfuse_tracer.get_tracer")
    @patch("src.agents.signal_ingester.get_openai_client")
    def test_returns_signal_analysis_on_success(
        self, mock_client_factory, mock_get_tracer, port_signal
    ):
        """LLM call succeeds → SignalAnalysis with all required fields."""
        mock_get_tracer.return_value = _make_mock_tracer()

        # Simulate gpt-4o-mini returning valid JSON
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps({
            "disruption_type": "port",
            "affected_kpis": ["lead_time", "freight_cost", "inventory"],
            "summary": "Port of Shanghai crane strike halting container operations in Asia-Pacific.",
            "severity_label": "high",
            "requires_full_crew": True,
        })
        mock_client.chat.completions.create.return_value = mock_resp

        from src.agents.signal_ingester import run
        result = run(port_signal)

        assert result.signal_id == port_signal.signal_id
        assert result.disruption_type == "port"
        assert result.severity_score == port_signal.severity_score
        assert result.severity_label == "high"
        assert result.requires_full_crew is True
        assert len(result.affected_kpis) >= 1
        assert result.summary != ""

    @patch("src.observability.langfuse_tracer.get_tracer")
    @patch("src.agents.signal_ingester.get_openai_client")
    def test_falls_back_on_invalid_json(
        self, mock_client_factory, mock_get_tracer, port_signal
    ):
        """LLM returns unparseable text → rule-based fallback, not an exception."""
        mock_get_tracer.return_value = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "This is not JSON at all."
        mock_client.chat.completions.create.return_value = mock_resp

        from src.agents.signal_ingester import run
        result = run(port_signal)

        # Should still return a valid SignalAnalysis, not raise
        assert result.signal_id == port_signal.signal_id
        assert result.requires_full_crew is True  # severity 8

    @patch("src.observability.langfuse_tracer.get_tracer")
    @patch("src.agents.signal_ingester.get_openai_client")
    def test_falls_back_on_api_error(
        self, mock_client_factory, mock_get_tracer, port_signal
    ):
        """OpenAI API error → rule-based fallback, not an exception."""
        import openai
        mock_get_tracer.return_value = _make_mock_tracer()
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.chat.completions.create.side_effect = openai.APIConnectionError(
            request=MagicMock()
        )

        from src.agents.signal_ingester import run
        result = run(port_signal)

        assert result.signal_id == port_signal.signal_id
        assert 1 <= result.severity_score <= 10

    def test_severity_label_low(self):
        from src.agents.signal_ingester import _severity_label
        assert _severity_label(1) == "low"
        assert _severity_label(3) == "low"

    def test_severity_label_medium(self):
        from src.agents.signal_ingester import _severity_label
        assert _severity_label(4) == "medium"
        assert _severity_label(6) == "medium"

    def test_severity_label_high(self):
        from src.agents.signal_ingester import _severity_label
        assert _severity_label(7) == "high"
        assert _severity_label(8) == "high"

    def test_severity_label_critical(self):
        from src.agents.signal_ingester import _severity_label
        assert _severity_label(9) == "critical"
        assert _severity_label(10) == "critical"

    def test_requires_full_crew_threshold_low(self, low_signal):
        """Severity 2 → requires_full_crew = False."""
        from src.agents.signal_ingester import _rule_based_fallback
        result = _rule_based_fallback(low_signal)
        assert result.requires_full_crew is False

    def test_requires_full_crew_threshold_boundary(self):
        """Severity 3 → False; severity 4 → True."""
        from src.agents.signal_ingester import _rule_based_fallback
        s3 = generate_mock_signal(disruption_type="weather", severity=3)
        s4 = generate_mock_signal(disruption_type="port", severity=4)
        assert _rule_based_fallback(s3).requires_full_crew is False
        assert _rule_based_fallback(s4).requires_full_crew is True

    def test_validate_passes_for_valid_analysis(self, port_signal):
        from src.agents.signal_ingester import validate_signal_analysis
        from src.models.outputs import SignalAnalysis
        analysis = SignalAnalysis(
            signal_id=port_signal.signal_id,
            disruption_type="port",
            region=port_signal.region,
            severity_score=8,
            severity_label="high",
            affected_kpis=["lead_time", "freight_cost"],
            summary="Test summary.",
            requires_full_crew=True,
        )
        # Should not raise
        validate_signal_analysis(analysis)

    def test_validate_raises_on_invalid_type(self, port_signal):
        from src.agents.signal_ingester import validate_signal_analysis
        from src.models.outputs import SignalAnalysis
        analysis = SignalAnalysis(
            signal_id=port_signal.signal_id,
            disruption_type="unknown_type",
            region=port_signal.region,
            severity_score=5,
            severity_label="medium",
            affected_kpis=["lead_time"],
            summary="Test.",
            requires_full_crew=True,
        )
        with pytest.raises(ValueError, match="disruption_type"):
            validate_signal_analysis(analysis)


# ---------------------------------------------------------------------------
# Task 4 — DynamoDB
# ---------------------------------------------------------------------------

class TestDynamoDB:
    def test_floats_to_decimal_simple(self):
        from src.persistence.dynamodb import _floats_to_decimal
        result = _floats_to_decimal({"score": 0.75, "count": 3})
        assert result["score"] == Decimal("0.75")
        assert result["count"] == 3  # int unchanged

    def test_floats_to_decimal_nested(self):
        from src.persistence.dynamodb import _floats_to_decimal
        nested = {"outer": {"inner": 0.5, "list": [1.0, 2.0, 3]}}
        result = _floats_to_decimal(nested)
        assert result["outer"]["inner"] == Decimal("0.5")
        assert result["outer"]["list"][0] == Decimal("1.0")
        assert result["outer"]["list"][2] == 3  # int unchanged

    def test_floats_to_decimal_list(self):
        from src.persistence.dynamodb import _floats_to_decimal
        result = _floats_to_decimal([0.1, 0.2, "text", 5])
        assert result[0] == Decimal("0.1")
        assert result[2] == "text"
        assert result[3] == 5

    @patch("src.persistence.dynamodb.get_dynamodb_client")
    def test_save_playbook_result_returns_true(self, mock_client_factory, port_signal):
        """save_playbook_result returns True when DynamoDB put_item succeeds."""
        from src.persistence.dynamodb import save_playbook_result
        from src.flows.disruption_flow import FlowState
        from src.agents.signal_ingester import _rule_based_fallback
        from src.agents.playbook_writer import run as run_pw

        # Build a minimal FlowState
        state = FlowState()
        state.signal = port_signal
        state.signal_analysis = _rule_based_fallback(port_signal)

        # Mock the playbook writer
        with patch("src.observability.langfuse_tracer.get_tracer", return_value=_make_mock_tracer()):
            state.playbook = run_pw(port_signal)

        # Mock DynamoDB resource chain
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_client_factory.return_value = mock_resource

        result = save_playbook_result(state)
        assert result is True
        mock_table.put_item.assert_called_once()

    @patch("src.persistence.dynamodb.get_dynamodb_client")
    def test_save_playbook_result_returns_false_on_error(
        self, mock_client_factory, port_signal
    ):
        """save_playbook_result returns False (not raises) when DynamoDB errors."""
        from src.persistence.dynamodb import save_playbook_result
        from src.flows.disruption_flow import FlowState
        from src.agents.playbook_writer import run as run_pw

        state = FlowState()
        state.signal = port_signal

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=_make_mock_tracer()):
            state.playbook = run_pw(port_signal)

        mock_table = MagicMock()
        mock_table.put_item.side_effect = Exception("DynamoDB connection refused")
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_client_factory.return_value = mock_resource

        result = save_playbook_result(state)
        assert result is False  # must not raise

    @patch("src.persistence.dynamodb.get_dynamodb_client")
    def test_get_playbook_returns_none_when_not_found(self, mock_client_factory):
        """get_playbook_by_signal_id returns None when item not in table."""
        from src.persistence.dynamodb import get_playbook_by_signal_id

        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": []}
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_client_factory.return_value = mock_resource

        result = get_playbook_by_signal_id("non-existent-id")
        assert result is None


# ---------------------------------------------------------------------------
# Task 5 — SNS Publisher
# ---------------------------------------------------------------------------

class TestSNSPublisher:
    @patch("src.notifications.sns_publisher.get_sns_client")
    def test_dev_mode_returns_true_without_calling_sns(
        self, mock_sns_factory, port_signal
    ):
        """In dev mode, publish_playbook_alert returns True without calling SNS."""
        from src.notifications.sns_publisher import publish_playbook_alert
        from src.agents.playbook_writer import run as run_pw

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=_make_mock_tracer()):
            playbook = run_pw(port_signal)

        # Force dev mode
        with patch("src.notifications.sns_publisher.get_settings") as mock_settings:
            mock_s = MagicMock()
            mock_s.is_development = True
            mock_s.sns_topic_critical = "arn:aws:sns:us-east-1:123:scdf-critical"
            mock_s.sns_topic_standard = "arn:aws:sns:us-east-1:123:scdf-standard"
            mock_settings.return_value = mock_s

            result = publish_playbook_alert(playbook)

        assert result is True
        mock_sns_factory.assert_not_called()  # no real SNS call in dev mode

    @patch("src.notifications.sns_publisher.get_sns_client")
    def test_low_risk_is_no_op(self, mock_sns_factory, port_signal):
        """Low-risk playbooks log only — SNS client never called."""
        from src.notifications.sns_publisher import publish_playbook_alert
        from src.models.outputs import Playbook, PlaybookAction

        playbook = Playbook(
            signal_id=port_signal.signal_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            dominant_scenario="P90 (best case)",
            overall_risk="low",
            actions=[
                PlaybookAction(
                    priority=1, action="Monitor", rationale="Low risk",
                    timeframe="1-week", confidence=0.5
                )
            ],
            bull_summary="", bear_summary="",
            key_uncertainties=[],
            ragas_context=[],
        )
        result = publish_playbook_alert(playbook)
        assert result is True
        mock_sns_factory.assert_not_called()

    @patch("src.notifications.sns_publisher.get_sns_client")
    def test_returns_false_on_client_error(self, mock_sns_factory, port_signal):
        """SNS ClientError → returns False, does not raise."""
        from src.notifications.sns_publisher import publish_playbook_alert
        from src.agents.playbook_writer import run as run_pw
        from botocore.exceptions import ClientError

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=_make_mock_tracer()):
            playbook = run_pw(port_signal)
        # Force playbook to high risk for SNS routing
        playbook = playbook.model_copy(update={"overall_risk": "high"})

        mock_sns = MagicMock()
        mock_sns.publish.side_effect = ClientError(
            {"Error": {"Code": "InvalidParameter", "Message": "bad ARN"}},
            "Publish",
        )
        mock_sns_factory.return_value = mock_sns

        with patch("src.notifications.sns_publisher.get_settings") as mock_settings:
            mock_s = MagicMock()
            mock_s.is_development = False
            mock_s.sns_topic_critical = "arn:aws:sns:us-east-1:123:scdf-critical"
            mock_s.sns_topic_standard = "arn:aws:sns:us-east-1:123:scdf-standard"
            mock_settings.return_value = mock_s

            result = publish_playbook_alert(playbook)

        assert result is False  # must not raise


# ---------------------------------------------------------------------------
# Task 7 — Lambda / Handlers
# ---------------------------------------------------------------------------

class TestLambdaHandler:
    @patch("src.flows.disruption_flow.run")
    @patch("src.observability.langfuse_tracer.get_tracer")
    def test_handler_returns_200_on_success(
        self, mock_get_tracer, mock_run_flow, port_signal
    ):
        """Valid EventBridge event → statusCode 200 and playbook JSON in body."""
        mock_get_tracer.return_value = _make_mock_tracer()

        from src.agents.playbook_writer import run as run_pw
        with patch("src.observability.langfuse_tracer.get_tracer", return_value=_make_mock_tracer()):
            expected_playbook = run_pw(port_signal)
        mock_run_flow.return_value = expected_playbook

        from src.handlers.signal_handler import handler
        event = {
            "source": "scdf.signals",
            "detail-type": "DisruptionSignal",
            "detail": json.loads(port_signal.model_dump_json()),
        }
        result = handler(event)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "signal_id" in body
        assert "overall_risk" in body

    def test_handler_returns_400_on_invalid_payload(self):
        """Malformed event detail → statusCode 400."""
        from src.handlers.signal_handler import handler
        event = {
            "source": "scdf.signals",
            "detail-type": "DisruptionSignal",
            "detail": {"invalid": "payload"},
        }
        result = handler(event)
        assert result["statusCode"] == 400

    def test_handler_returns_500_on_flow_error(self, port_signal):
        """Flow exception → statusCode 500."""
        # Patch flow.run where it is lazily imported inside the handler
        with patch("src.flows.disruption_flow.run", side_effect=RuntimeError("flow failure")):
            from src.handlers.signal_handler import handler
            event = {
                "source": "scdf.signals",
                "detail-type": "DisruptionSignal",
                "detail": json.loads(port_signal.model_dump_json()),
            }
            result = handler(event)

        assert result["statusCode"] == 500

    @patch("src.flows.disruption_flow.run")
    def test_local_invoke_returns_dict(self, mock_run_flow, port_signal):
        """local_invoke wraps signal in EventBridge format and returns a response dict."""
        from src.agents.playbook_writer import run as run_pw
        with patch("src.observability.langfuse_tracer.get_tracer", return_value=_make_mock_tracer()):
            mock_run_flow.return_value = run_pw(port_signal)

        from src.handlers.signal_handler import local_invoke
        result = local_invoke(port_signal)

        assert isinstance(result, dict)
        assert "statusCode" in result
        assert result["statusCode"] == 200


# ---------------------------------------------------------------------------
# Integration tests (require live Redis)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRedisIntegration:
    def test_publish_and_consume_round_trip(self, port_signal):
        """
        Publish a signal to Redis stream, consume it with consume_once(),
        verify handler received the correct signal_id.
        """
        try:
            from src.ingestion.redis_consumer import (
                publish_signal, consume_once, get_redis_client
            )
            # Verify Redis is actually available before running
            client = get_redis_client()
        except RuntimeError:
            pytest.skip("UPSTASH_REDIS_URL not configured — skipping Redis integration test")

        received = []

        def capture(signal: DisruptionSignal):
            received.append(signal)

        publish_signal(port_signal)
        count = consume_once(capture)

        assert count >= 1
        assert any(s.signal_id == port_signal.signal_id for s in received)
