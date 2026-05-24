"""
DynamoDB persistence layer for SCDF flow run results.

Table design:
  Table:    scdf-disruptions
  PK:       signal_id (str)
  SK:       created_at (ISO timestamp str)
  GSI-1:    region-created_at-index (for planner dashboard region queries)
  GSI-2:    risk_level-created_at-index (for alert dashboards)

All Pydantic models are serialised via .model_dump() → floats converted to
Decimal (boto3 DynamoDB client rejects Python floats).

All public functions return bool/dict/list and never raise — infra failures
are logged and callers always get a safe fallback response.
"""

import logging
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from src.config.settings import get_settings

if TYPE_CHECKING:
    # Avoid circular import: FlowState imports persistence lazily inside persist_result
    from src.flows.disruption_flow import FlowState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table + index constants
# ---------------------------------------------------------------------------

_TABLE_NAME_FALLBACK = "scdf-disruptions"

# GSI names must match the definitions in ensure_table_exists()
GSI_REGION_INDEX = "region-created_at-index"
GSI_RISK_INDEX = "risk_level-created_at-index"


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def get_dynamodb_client():
    """
    Return a boto3 DynamoDB resource using settings credentials.

    Supports real AWS and local DynamoDB (DYNAMODB_ENDPOINT_URL setting).
    """
    settings = get_settings()
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    if settings.dynamodb_endpoint_url:
        # Local DynamoDB (e.g. dynamodb-local or LocalStack)
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
    return boto3.resource("dynamodb", **kwargs)


# ---------------------------------------------------------------------------
# Table provisioning
# ---------------------------------------------------------------------------

def ensure_table_exists() -> None:
    """
    Create the scdf-disruptions table + both GSIs if they do not exist.

    Uses PAY_PER_REQUEST billing to stay within the AWS always-free tier.
    Waits for the table to become ACTIVE before returning.
    Idempotent — safe to call on every application startup.
    """
    settings = get_settings()
    table_name = settings.dynamodb_table_disruptions or _TABLE_NAME_FALLBACK
    dynamodb = get_dynamodb_client()

    try:
        table = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "signal_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "signal_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
                {"AttributeName": "region", "AttributeType": "S"},
                {"AttributeName": "risk_level", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": GSI_REGION_INDEX,
                    "KeySchema": [
                        {"AttributeName": "region", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": GSI_RISK_INDEX,
                    "KeySchema": [
                        {"AttributeName": "risk_level", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        logger.info(f"Creating DynamoDB table '{table_name}'...")
        # Wait until the table is fully active before continuing
        table.wait_until_exists()
        logger.info(f"DynamoDB table '{table_name}' is now ACTIVE")
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceInUseException":
            logger.debug(f"DynamoDB table '{table_name}' already exists")
        else:
            logger.error(f"DynamoDB table creation failed: {exc}")
            raise


# ---------------------------------------------------------------------------
# Decimal conversion (DynamoDB rejects Python floats)
# ---------------------------------------------------------------------------

def _floats_to_decimal(obj: Any) -> Any:
    """
    Recursively convert all float values in a nested dict/list to Decimal.

    DynamoDB's boto3 client raises TypeError on Python floats, so every
    serialised Pydantic model must pass through this function before upsert.
    """
    if isinstance(obj, float):
        try:
            return Decimal(str(obj))
        except InvalidOperation:
            return Decimal("0")
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Read / write helpers
# ---------------------------------------------------------------------------

def save_playbook_result(state: "FlowState") -> bool:
    """
    Serialise the complete FlowState and upsert it to DynamoDB.

    Includes all Pydantic models (signal, analysis, scenarios, impact, playbook,
    ragas_score) so the full run context is queryable from the dashboard API.

    Args:
        state: The completed FlowState from a DisruptionFlow run.

    Returns:
        True on success, False on any failure. Never raises.
    """
    if state.playbook is None or state.signal is None:
        logger.warning("save_playbook_result called with incomplete state — skipping")
        return False

    settings = get_settings()
    table_name = settings.dynamodb_table_disruptions or _TABLE_NAME_FALLBACK

    try:
        item: dict[str, Any] = {
            "signal_id": state.signal.signal_id,
            "created_at": state.started_at,
            "run_id": state.run_id,
            "completed_at": state.completed_at or "",
            "fast_path": state.fast_path,
            "region": state.signal.region,
            "risk_level": state.playbook.overall_risk,
            "disruption_type": state.signal.disruption_type,
            # Full serialised sub-documents
            "signal": state.signal.model_dump(mode="json"),
            "playbook": state.playbook.model_dump(mode="json"),
        }

        # Optional sub-documents — present only if the step ran
        if state.signal_analysis:
            item["signal_analysis"] = state.signal_analysis.model_dump(mode="json")
        if state.scenario_set:
            item["scenario_set"] = state.scenario_set.model_dump(mode="json")
        if state.impact_analysis:
            item["impact_analysis"] = state.impact_analysis.model_dump(mode="json")
        if state.bull_position:
            item["bull_position"] = state.bull_position.model_dump(mode="json")
        if state.bear_position:
            item["bear_position"] = state.bear_position.model_dump(mode="json")
        if state.ragas_score:
            item["ragas_score"] = state.ragas_score.model_dump(mode="json")

        # Convert floats → Decimal for DynamoDB compatibility
        item = _floats_to_decimal(item)

        dynamodb = get_dynamodb_client()
        table = dynamodb.Table(table_name)
        table.put_item(Item=item)
        logger.info(
            f"[dynamodb] saved run signal_id={state.signal.signal_id} "
            f"risk={state.playbook.overall_risk}"
        )
        return True

    except Exception as exc:
        logger.error(f"[dynamodb] save failed for {state.signal.signal_id}: {exc}")
        return False


def get_playbook_by_signal_id(signal_id: str) -> dict | None:
    """
    Retrieve a playbook result item by signal_id (query on PK).

    Returns the most recent item if multiple runs exist for the same signal_id.

    Args:
        signal_id: The DisruptionSignal UUID to look up.

    Returns:
        The full DynamoDB item as a plain dict, or None if not found.
    """
    settings = get_settings()
    table_name = settings.dynamodb_table_disruptions or _TABLE_NAME_FALLBACK

    try:
        dynamodb = get_dynamodb_client()
        table = dynamodb.Table(table_name)
        response = table.query(
            KeyConditionExpression="signal_id = :sid",
            ExpressionAttributeValues={":sid": signal_id},
            ScanIndexForward=False,  # descending by SK (created_at) → most recent first
            Limit=1,
        )
        items = response.get("Items", [])
        return dict(items[0]) if items else None
    except Exception as exc:
        logger.error(f"[dynamodb] get failed for signal_id={signal_id}: {exc}")
        return None


def list_recent_playbooks(limit: int = 10) -> list[dict]:
    """
    Scan the table and return the most recent `limit` playbook results.

    Note: DynamoDB Scan is O(table size). Acceptable at dev scale; for
    production, implement a GSI on created_at or use a time-series index.

    Args:
        limit: Maximum number of items to return.

    Returns:
        List of DynamoDB items as plain dicts, sorted newest-first.
    """
    settings = get_settings()
    table_name = settings.dynamodb_table_disruptions or _TABLE_NAME_FALLBACK

    try:
        dynamodb = get_dynamodb_client()
        table = dynamodb.Table(table_name)
        response = table.scan(Limit=limit * 3)  # over-scan then sort
        items = response.get("Items", [])
        # Sort by created_at descending (ISO strings sort lexicographically)
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return [dict(item) for item in items[:limit]]
    except Exception as exc:
        logger.error(f"[dynamodb] list_recent_playbooks failed: {exc}")
        return []
