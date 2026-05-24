"""
AWS Lambda handler for SCDF signal processing.

In production this function is invoked by an EventBridge rule that watches
for events with source="scdf.signals" and detail-type="DisruptionSignal".

EventBridge event format:
{
  "source": "scdf.signals",
  "detail-type": "DisruptionSignal",
  "detail": {
    "signal_id": "...",
    "disruption_type": "port",
    "region": "Asia-Pacific",
    "severity_score": 8,
    "description": "...",
    "affected_routes": [...],
    "timestamp": "2026-01-01T00:00:00+00:00",
    "source": "upstash-redis"
  }
}

For local development and tests, use local_invoke() which wraps the handler
with a synthetic EventBridge event dict.
"""

import json
import logging

from src.signals.mock_generator import DisruptionSignal

logger = logging.getLogger(__name__)


def handler(event: dict, context=None) -> dict:
    """
    Lambda entry point — parses an EventBridge event and runs the SCDF Flow.

    Supports two event shapes:
      - EventBridge format: event["detail"] contains the signal fields
      - Direct invocation: event is the signal dict itself (for local testing)

    Args:
        event:   EventBridge event dict (or direct signal dict for local use).
        context: Lambda context object (unused, can be None in local testing).

    Returns:
        {"statusCode": 200, "body": "<playbook JSON>"} on success.
        {"statusCode": 500, "body": "<error message>"}  on failure.
    """
    # Extract signal fields from EventBridge or direct invocation
    detail = event.get("detail", event)
    signal_id = detail.get("signal_id", "unknown")
    logger.info(f"[lambda] processing signal_id={signal_id}")

    try:
        signal = DisruptionSignal(**detail)
    except Exception as exc:
        logger.error(f"[lambda] failed to parse signal: {exc}")
        return {"statusCode": 400, "body": f"Invalid signal payload: {exc}"}

    try:
        # Import lazily to avoid circular imports at module load time
        from src.flows.disruption_flow import run as run_flow

        playbook = run_flow(signal)

        logger.info(
            f"[lambda] completed signal_id={signal_id} "
            f"risk={playbook.overall_risk} "
            f"dominant_scenario={playbook.dominant_scenario}"
        )
        return {
            "statusCode": 200,
            "body": playbook.model_dump_json(),
        }

    except Exception as exc:
        logger.error(f"[lambda] flow failed for signal_id={signal_id}: {exc}")
        return {
            "statusCode": 500,
            "body": str(exc),
        }


def local_invoke(signal: DisruptionSignal) -> dict:
    """
    Invoke the Lambda handler locally without real Lambda infrastructure.

    Wraps the signal in a synthetic EventBridge event dict and calls handler().
    Used by scripts/run_pipeline.py and integration tests.

    Args:
        signal: The DisruptionSignal to process.

    Returns:
        The handler's return dict {"statusCode": ..., "body": ...}.
    """
    synthetic_event = {
        "source": "scdf.signals",
        "detail-type": "DisruptionSignal",
        "detail": json.loads(signal.model_dump_json()),
    }
    return handler(synthetic_event, context=None)
