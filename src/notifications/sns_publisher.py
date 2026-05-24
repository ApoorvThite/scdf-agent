"""
SNS notification publisher for SCDF playbook alerts.

Routes alerts to planners via SNS topics based on risk level:
  critical/high → sns_topic_critical (immediate alert — Slack/pager)
  medium        → sns_topic_standard (standard alert — email digest)
  low           → no-op (logged only)

In ENVIRONMENT=development mode, all publishes are replaced with log output
so no real SNS infrastructure is required for local development or testing.
"""

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

from src.config.settings import get_settings
from src.models.outputs import Playbook

if TYPE_CHECKING:
    from src.evaluation.ragas_scorer import RAGASScore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Topic routing map
# ---------------------------------------------------------------------------

def _get_topic_map() -> dict[str, str | None]:
    """Build risk-level → SNS topic ARN mapping from settings."""
    settings = get_settings()
    return {
        "critical": settings.sns_topic_critical or None,
        "high": settings.sns_topic_critical or None,  # critical and high share one topic
        "medium": settings.sns_topic_standard or None,
        "low": None,  # no SNS notification for low-risk events
    }


# ---------------------------------------------------------------------------
# SNS client factory
# ---------------------------------------------------------------------------

def get_sns_client():
    """Return a boto3 SNS client using settings credentials."""
    settings = get_settings()
    kwargs = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("sns", **kwargs)


# ---------------------------------------------------------------------------
# Alert publisher
# ---------------------------------------------------------------------------

def publish_playbook_alert(
    playbook: Playbook,
    ragas_score: "RAGASScore | None" = None,
) -> bool:
    """
    Publish a structured playbook alert to the appropriate SNS topic.

    In development mode (ENVIRONMENT=development): logs the alert message
    instead of publishing, so no real SNS setup is needed locally.

    In production mode: publishes to the SNS topic mapped to the risk level.

    Args:
        playbook:    The completed Playbook from the crew run.
        ragas_score: Optional RAGAS evaluation score for the playbook.

    Returns:
        True on success (including dev-mode log), False on publish failure.
        Never raises — infra failures are logged and return False.
    """
    settings = get_settings()
    topic_map = _get_topic_map()
    topic_arn = topic_map.get(playbook.overall_risk)

    if topic_arn is None and playbook.overall_risk != "low":
        # Risk level is medium/high/critical but no ARN configured yet
        logger.info(
            f"[sns] no topic ARN configured for risk='{playbook.overall_risk}' "
            f"signal={playbook.signal_id} — skipping"
        )
        return True

    if topic_arn is None:
        # Low risk — intentional no-op
        logger.info(
            f"[sns] low-risk signal={playbook.signal_id} — no notification sent"
        )
        return True

    # Build the structured alert message
    top_action = playbook.actions[0] if playbook.actions else None
    summary_actions = " | ".join(
        a.action for a in playbook.actions[:3]
    )[:200]

    message_body = {
        "signal_id": playbook.signal_id,
        "risk_level": playbook.overall_risk,
        "dominant_scenario": playbook.dominant_scenario,
        "top_action": top_action.action if top_action else "No actions generated",
        "ragas_passed": ragas_score.passed if ragas_score else None,
        "generated_at": playbook.generated_at,
        "playbook_summary": summary_actions,
    }
    subject = f"SCDF Alert: {playbook.overall_risk.upper()} disruption [{playbook.signal_id[:8]}]"
    message_json = json.dumps(message_body, indent=2)

    # Development mode: log instead of publish
    if settings.is_development:
        logger.info(
            f"[sns] [DEV MODE] would publish to topic={topic_arn}\n"
            f"  Subject: {subject}\n"
            f"  Message: {message_json}"
        )
        return True

    # Production mode: real SNS publish
    try:
        client = get_sns_client()
        client.publish(
            TopicArn=topic_arn,
            Subject=subject,
            Message=message_json,
        )
        logger.info(
            f"[sns] published {playbook.overall_risk} alert for "
            f"signal={playbook.signal_id} → {topic_arn}"
        )
        return True
    except ClientError as exc:
        logger.error(f"[sns] publish failed: {exc}")
        return False
    except Exception as exc:
        logger.error(f"[sns] unexpected error: {exc}")
        return False
