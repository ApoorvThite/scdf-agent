"""
One-time AWS resource provisioning script for SCDF.

Provisions in order:
  1. DynamoDB table (scdf-disruptions) with GSIs
  2. S3 bucket for playbook JSONs
  3. SNS topics: scdf-critical and scdf-standard
  4. EventBridge rule for signal routing

Safe to run multiple times — all operations are idempotent.
Partial setup is acceptable — failures are logged and the script continues.

Usage:
    python -m scripts.setup_aws
"""

import sys

import boto3
from botocore.exceptions import ClientError
from rich.console import Console
from rich.table import Table

from src.config.settings import get_settings
from src.persistence.dynamodb import ensure_table_exists

console = Console()


def _check(label: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    """Return a tuple for the results table."""
    return (label, ok, detail)


def provision_dynamodb() -> tuple[str, bool, str]:
    """Create the DynamoDB table. Returns (label, success, detail)."""
    settings = get_settings()
    table_name = settings.dynamodb_table_disruptions
    try:
        ensure_table_exists()
        return _check(f"DynamoDB: {table_name}", True, "ready")
    except Exception as exc:
        return _check(f"DynamoDB: {table_name}", False, str(exc)[:80])


def provision_s3() -> tuple[str, bool, str]:
    """Create the S3 bucket for playbook storage."""
    settings = get_settings()
    bucket_name = settings.s3_bucket_playbooks
    region = settings.aws_region

    kwargs = {"region_name": region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

    try:
        s3 = boto3.client("s3", **kwargs)
        # us-east-1 requires no LocationConstraint
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        return _check(f"S3: {bucket_name}", True, f"created in {region}")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            return _check(f"S3: {bucket_name}", True, "already exists")
        return _check(f"S3: {bucket_name}", False, str(exc)[:80])
    except Exception as exc:
        return _check(f"S3: {bucket_name}", False, str(exc)[:80])


def provision_sns_topics() -> list[tuple[str, bool, str]]:
    """Create scdf-critical and scdf-standard SNS topics. Returns ARNs."""
    settings = get_settings()
    region = settings.aws_region
    kwargs = {"region_name": region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

    results = []
    try:
        sns = boto3.client("sns", **kwargs)
        for topic_name in ["scdf-critical", "scdf-standard"]:
            try:
                resp = sns.create_topic(Name=topic_name)
                arn = resp["TopicArn"]
                results.append(_check(f"SNS: {topic_name}", True, arn))
                console.print(f"  → Add to .env: [bold]SNS_TOPIC_{topic_name.split('-')[1].upper()}={arn}[/bold]")
            except ClientError as exc:
                results.append(_check(f"SNS: {topic_name}", False, str(exc)[:80]))
    except Exception as exc:
        results.append(_check("SNS: connection", False, str(exc)[:80]))

    return results


def provision_eventbridge() -> tuple[str, bool, str]:
    """Create an EventBridge rule that matches SCDF signal events."""
    settings = get_settings()
    region = settings.aws_region
    kwargs = {"region_name": region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

    try:
        eb = boto3.client("events", **kwargs)
        import json
        pattern = json.dumps({
            "source": ["scdf.signals"],
            "detail-type": ["DisruptionSignal"],
        })
        eb.put_rule(
            Name="scdf-signal-rule",
            EventPattern=pattern,
            State="ENABLED",
            Description="Routes SCDF DisruptionSignal events to the crew flow",
        )
        return _check("EventBridge: scdf-signal-rule", True, "enabled")
    except ClientError as exc:
        return _check("EventBridge: scdf-signal-rule", False, str(exc)[:80])
    except Exception as exc:
        return _check("EventBridge: scdf-signal-rule", False, str(exc)[:80])


def main() -> int:
    console.rule("[bold cyan]SCDF AWS Resource Provisioning[/bold cyan]")

    settings = get_settings()
    if not settings.aws_access_key_id:
        console.print(
            "[yellow]⚠ AWS_ACCESS_KEY_ID not set — provisioning may fail.[/yellow]\n"
            "  Set credentials in .env to create real AWS resources."
        )

    # Run all provisioning steps — collect results regardless of individual failures
    results = []
    results.append(provision_dynamodb())
    results.append(provision_s3())
    results.extend(provision_sns_topics())
    results.append(provision_eventbridge())

    # Print checklist
    table = Table(title="Provisioning Results", show_header=True, header_style="bold blue")
    table.add_column("Resource", style="cyan", min_width=30)
    table.add_column("Status", justify="center", min_width=8)
    table.add_column("Detail", style="dim")

    passed = 0
    for label, ok, detail in results:
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        table.add_row(label, status, detail)
        if ok:
            passed += 1

    console.print()
    console.print(table)
    console.print(f"\n[bold]{passed}/{len(results)}[/bold] resources provisioned successfully")

    return 0 if passed >= 1 else 1


if __name__ == "__main__":
    sys.exit(main())
