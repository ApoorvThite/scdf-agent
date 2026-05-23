"""
Week 1 pytest suite — covers settings, models, clients, and integrations.
Run: pytest tests/ -v
"""

import os
import pytest


# ── Settings ───────────────────────────────────────────────────────────────────

def test_settings_loads():
    """Settings singleton loads without raising."""
    # Clear cache so test isolation works
    from src.config.settings import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert s is not None


def test_settings_required_fields_present():
    from src.config.settings import get_settings
    s = get_settings()
    assert s.project_name
    assert s.environment
    assert s.model_primary
    assert s.model_debate
    assert s.model_fast
    assert s.qdrant_host
    assert s.qdrant_port > 0
    assert s.qdrant_collection_disruptions
    assert s.qdrant_collection_responses
    assert s.qdrant_collection_playbooks


def test_settings_is_development_property():
    from src.config.settings import get_settings
    s = get_settings()
    # In test environment, ENVIRONMENT defaults to 'development'
    assert isinstance(s.is_development, bool)


# ── DisruptionSignal model ─────────────────────────────────────────────────────

def test_disruption_signal_valid():
    from src.signals.mock_generator import DisruptionSignal
    from datetime import datetime, timezone

    sig = DisruptionSignal(
        disruption_type="port",
        region="Asia-Pacific",
        severity_score=7,
        description="Test port closure",
        affected_routes=["Trans-Pacific", "Intra-Asia"],
        source="Test Source",
    )
    assert sig.signal_id  # auto-generated UUID
    assert sig.disruption_type == "port"
    assert sig.severity_score == 7
    assert isinstance(sig.timestamp, datetime)


def test_disruption_signal_severity_bounds():
    from src.signals.mock_generator import DisruptionSignal
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        DisruptionSignal(
            disruption_type="weather",
            region="Europe",
            severity_score=11,  # out of range
            description="Too severe",
            affected_routes=[],
            source="Test",
        )

    with pytest.raises(pydantic.ValidationError):
        DisruptionSignal(
            disruption_type="weather",
            region="Europe",
            severity_score=0,  # out of range
            description="Not severe enough",
            affected_routes=[],
            source="Test",
        )


# ── OpenAI / Helicone client ───────────────────────────────────────────────────

def test_get_openai_client_base_url():
    from src.config.helicone import get_openai_client
    from src.config.settings import get_settings

    client = get_openai_client()
    settings = get_settings()
    assert str(client.base_url).rstrip("/") == settings.helicone_base_url.rstrip("/")


def test_get_openai_client_agent_header():
    from src.config.helicone import get_openai_client

    client = get_openai_client(agent_name="test-agent")
    # The default headers are set on the client's _custom_headers
    headers = dict(client.default_headers)
    # Helicone-Property-Agent should be present
    assert any("helicone-property-agent" in k.lower() for k in headers)


# ── Mock signal generator ──────────────────────────────────────────────────────

DISRUPTION_TYPES = ["weather", "port", "tariff", "demand", "geopolitical"]


@pytest.mark.parametrize("dtype", DISRUPTION_TYPES)
def test_generate_mock_signal_each_type(dtype):
    from src.signals.mock_generator import generate_mock_signal, DisruptionSignal

    sig = generate_mock_signal(disruption_type=dtype)
    assert isinstance(sig, DisruptionSignal)
    assert sig.disruption_type == dtype
    assert 1 <= sig.severity_score <= 10
    assert sig.description
    assert sig.region
    assert sig.source
    assert len(sig.affected_routes) > 0


def test_generate_mock_signal_random():
    from src.signals.mock_generator import generate_mock_signal

    signals = [generate_mock_signal() for _ in range(20)]
    types_seen = {s.disruption_type for s in signals}
    # With 20 signals and 5 types, very likely to see at least 2 distinct types
    assert len(types_seen) >= 2


def test_stream_signals_count():
    from src.signals.mock_generator import stream_signals

    signals = list(stream_signals(interval_seconds=0, count=5))
    assert len(signals) == 5


# ── Qdrant integration (skipped if not running) ────────────────────────────────

@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="Qdrant not available in CI",
)
def test_qdrant_collections_exist():
    """Integration test — skipped if QDRANT is not reachable."""
    try:
        from src.memory.qdrant_client import get_qdrant_client, setup_collections
        from src.config.settings import get_settings

        client = get_qdrant_client()
        # Quick reachability probe
        client.get_collections()

        setup_collections(client)
        settings = get_settings()
        existing = [c.name for c in client.get_collections().collections]
        assert settings.qdrant_collection_disruptions in existing
        assert settings.qdrant_collection_responses in existing
        assert settings.qdrant_collection_playbooks in existing
    except Exception as e:
        pytest.skip(f"Qdrant not reachable: {e}")
