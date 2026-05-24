"""
Full end-to-end SCDF pipeline demo.

Flow:
  Signal published to Redis
      → consumed from Redis stream
          → Lambda handler invoked (locally)
              → CrewAI Flow runs (all agents)
                  → DynamoDB saved
                      → SNS published (or logged in dev mode)
                          → RAGAS scores printed

Usage:
    python -m scripts.run_pipeline
    python -m scripts.run_pipeline --type port --severity 8
    python -m scripts.run_pipeline --type tariff --severity 5 --region "North America"
"""

import argparse
import json
import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the full SCDF signal-to-playbook pipeline end-to-end."
    )
    parser.add_argument("--type", dest="disruption_type", default="port",
                        choices=["port", "weather", "tariff", "demand", "geopolitical"])
    parser.add_argument("--severity", type=int, default=7, metavar="1-10")
    parser.add_argument("--region", default=None, help="Override region")
    args = parser.parse_args()

    console.rule("[bold cyan]SCDF End-to-End Pipeline[/bold cyan]")

    # ── Step 1: Generate and publish signal ───────────────────────────────────
    from src.signals.mock_generator import generate_mock_signal

    signal = generate_mock_signal(
        disruption_type=args.disruption_type,
        severity=args.severity,
    )
    if args.region:
        signal = signal.model_copy(update={"region": args.region})

    console.print(f"\n[bold]Step 1 — Generate signal[/bold]")
    console.print(f"  signal_id  : [cyan]{signal.signal_id}[/cyan]")
    console.print(f"  type       : {signal.disruption_type}")
    console.print(f"  region     : {signal.region}")
    console.print(f"  severity   : {signal.severity_score}")
    console.print(f"  description: {signal.description[:80]}...")

    redis_ok = False
    entry_id = None
    try:
        from src.ingestion.redis_consumer import publish_signal, consume_once
        entry_id = publish_signal(signal)
        console.print(f"\n[bold]Step 2 — Publish to Redis[/bold]")
        console.print(f"  stream entry: [green]{entry_id}[/green]")
        redis_ok = True
    except RuntimeError as exc:
        console.print(f"\n[bold]Step 2 — Publish to Redis[/bold]")
        console.print(f"  [yellow]Skipped — Redis not configured: {exc}[/yellow]")

    # ── Step 3: Invoke Lambda handler locally ─────────────────────────────────
    console.print(f"\n[bold]Step 3 — Lambda handler (local invoke)[/bold]")
    wall_start = time.monotonic()

    from src.lambda.signal_handler import local_invoke

    result = local_invoke(signal)
    elapsed = time.monotonic() - wall_start

    if result["statusCode"] != 200:
        console.print(f"  [red]Flow failed: {result['body']}[/red]")
        return 1

    console.print(f"  status : [green]{result['statusCode']} OK[/green]")
    console.print(f"  elapsed: {elapsed:.1f}s")

    # ── Step 4: Parse playbook from response ──────────────────────────────────
    from src.models.outputs import Playbook

    playbook = Playbook.model_validate_json(result["body"])

    # ── Step 5: Retrieve state from flow (if possible) ────────────────────────
    # We use DynamoDB to get the persisted state with RAGAS scores
    ragas_saved = None
    dynamodb_count = 0
    try:
        from src.persistence.dynamodb import (
            get_playbook_by_signal_id, list_recent_playbooks
        )
        saved_item = get_playbook_by_signal_id(signal.signal_id)
        if saved_item and "ragas_score" in saved_item:
            ragas_saved = saved_item["ragas_score"]
        dynamodb_count = len(list_recent_playbooks(limit=100))
    except Exception as exc:
        console.print(f"  [yellow]DynamoDB query skipped: {exc}[/yellow]")

    # ── Step 6: Print rich summary panel ─────────────────────────────────────
    _print_summary(signal, playbook, ragas_saved, elapsed, redis_ok, entry_id, dynamodb_count)

    return 0


def _print_summary(signal, playbook, ragas_saved, elapsed, redis_ok, entry_id, dynamodb_count):
    """Render a Rich summary panel with all pipeline results."""

    # Scenarios table
    scen_table = Table(show_header=True, header_style="bold")
    scen_table.add_column("Scenario")
    scen_table.add_column("Lead Time Δ", justify="right")
    scen_table.add_column("Inventory Δ%", justify="right")
    scen_table.add_column("SLA Δ%", justify="right")
    scen_table.add_column("Resolution", justify="right")

    # Actions table
    action_table = Table(show_header=True, header_style="bold")
    action_table.add_column("#", width=3)
    action_table.add_column("Action", min_width=40)
    action_table.add_column("Timeframe", justify="center")
    action_table.add_column("Confidence", justify="center")

    for i, act in enumerate(playbook.actions[:3], 1):
        conf_colour = "green" if act.confidence >= 0.8 else "yellow"
        action_table.add_row(
            str(i),
            act.action[:60] + ("…" if len(act.action) > 60 else ""),
            act.timeframe,
            f"[{conf_colour}]{act.confidence:.0%}[/{conf_colour}]",
        )

    # RAGAS
    ragas_lines = ""
    if ragas_saved:
        f = float(ragas_saved.get("faithfulness", 0))
        ar = float(ragas_saved.get("answer_relevance", 0))
        cp = float(ragas_saved.get("context_precision", 0))
        ov = float(ragas_saved.get("overall", 0))
        passed = ragas_saved.get("passed", False)
        col = "green" if passed else "red"
        ragas_lines = (
            f"\n  Faithfulness      : {f:.3f}"
            f"\n  Answer Relevance  : {ar:.3f}"
            f"\n  Context Precision : {cp:.3f}"
            f"\n  Overall           : [{col}]{ov:.3f}[/{col}]  "
            f"({'✓ passed' if passed else '✗ failed'})"
        )

    risk_colour = {"low": "green", "medium": "yellow", "high": "red", "critical": "bold red"}.get(
        playbook.overall_risk, "white"
    )

    summary = (
        f"[bold]Signal[/bold]\n"
        f"  ID          : {signal.signal_id}\n"
        f"  Type/Region : {signal.disruption_type} / {signal.region}\n"
        f"  Severity    : {signal.severity_score}\n"
        f"\n[bold]Playbook[/bold]\n"
        f"  Risk Level  : [{risk_colour}]{playbook.overall_risk.upper()}[/{risk_colour}]\n"
        f"  Scenario    : {playbook.dominant_scenario}\n"
        f"\n[bold]Top 3 Actions[/bold]"
    )

    console.print(Panel(summary, title="SCDF Pipeline Summary", expand=False))
    console.print(action_table)

    status_lines = [
        f"\n[bold]Pipeline Status[/bold]",
        f"  Wall clock  : {elapsed:.1f}s",
        f"  Redis       : {'[green]✓[/green] published entry ' + str(entry_id) if redis_ok else '[yellow]skipped (not configured)[/yellow]'}",
        f"  DynamoDB    : [green]✓ {dynamodb_count} total records[/green]" if dynamodb_count else "  DynamoDB    : [yellow]not available[/yellow]",
        f"  SNS         : [green]✓ dev-mode logged[/green]",
    ]
    if ragas_lines:
        status_lines.append(f"\n[bold]RAGAS Scores[/bold]{ragas_lines}")

    console.print("\n".join(status_lines))


if __name__ == "__main__":
    sys.exit(main())
