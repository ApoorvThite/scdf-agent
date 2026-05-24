"""
Full crew demo — runs the complete 6-agent SCDF pipeline and renders a
6-panel Rich report: Signal → Scenarios → Precedents → Debate → Playbook → Quality.

Usage:
    python -m scripts.run_full_crew                      # random signal
    python -m scripts.run_full_crew --type port --severity 8
    python -m scripts.run_full_crew --type weather --severity 6
"""

import argparse
import sys
import time
import uuid
from datetime import datetime, timezone

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


def _scenario_panel(scenario_set) -> Panel:
    """Render the P10/P50/P90 scenario set as a side-by-side panel."""
    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("Scenario", style="bold")
    table.add_column("Lead Time +d", justify="right")
    table.add_column("Inventory %", justify="right")
    table.add_column("Svc Level %", justify="right")
    table.add_column("Resolution d", justify="right")

    for label, scenario in [
        ("P10 (worst)", scenario_set.p10),
        ("P50 (base)", scenario_set.p50),
        ("P90 (best)", scenario_set.p90),
    ]:
        color = "red" if "P10" in label else ("green" if "P90" in label else "yellow")
        table.add_row(
            f"[{color}]{label}[/{color}]",
            str(scenario.lead_time_impact_days),
            f"{scenario.inventory_impact_pct:+.1f}",
            f"{scenario.service_level_impact_pct:+.1f}",
            str(scenario.resolution_days_estimate),
        )

    return Panel(table, title="[bold]Scenario Forecast (P10/P50/P90)[/bold]", border_style="cyan")


def _precedents_panel(impact_analysis) -> Panel:
    """Render top-3 historical precedents."""
    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Similarity", justify="right")
    table.add_column("Region")
    table.add_column("Description", ratio=3)
    table.add_column("Resolution d", justify="right")
    table.add_column("Outcome")

    for p in impact_analysis.precedents:
        outcome_color = "green" if p.outcome == "successful" else ("yellow" if p.outcome == "partial" else "red")
        table.add_row(
            f"{p.similarity_score:.2f}",
            p.region,
            p.description[:70] + ("…" if len(p.description) > 70 else ""),
            str(p.resolution_days),
            f"[{outcome_color}]{p.outcome}[/{outcome_color}]",
        )

    risk_color = "red" if impact_analysis.risk_level in ("high", "critical") else "yellow"
    title = (
        f"[bold]Historical Precedents[/bold] — "
        f"Risk: [{risk_color}]{impact_analysis.risk_level.upper()}[/{risk_color}]"
    )
    return Panel(table, title=title, border_style="magenta")


def _debate_panel(bull, bear) -> Panel:
    """Render the bull vs bear debate side by side."""
    bull_text = Text()
    bull_text.append("BULL CASE\n", style="bold green")
    bull_text.append(f"Confidence: {bull.confidence:.0%}\n", style="green")
    bull_text.append(f"Recommends: {bull.recommended_scenario}\n\n", style="green")
    bull_text.append(f"Thesis:\n{bull.thesis}\n\n", style="white")
    bull_text.append("Evidence:\n", style="bold")
    for e in bull.key_evidence:
        bull_text.append(f"  • {e}\n", style="dim white")
    bull_text.append(f"\nDissenting risk:\n{bull.dissenting_risk}", style="italic dim")

    bear_text = Text()
    bear_text.append("BEAR CASE\n", style="bold red")
    bear_text.append(f"Confidence: {bear.confidence:.0%}\n", style="red")
    bear_text.append(f"Recommends: {bear.recommended_scenario}\n\n", style="red")
    bear_text.append(f"Thesis:\n{bear.thesis}\n\n", style="white")
    bear_text.append("Evidence:\n", style="bold")
    for e in bear.key_evidence:
        bear_text.append(f"  • {e}\n", style="dim white")
    bear_text.append(f"\nDissenting risk:\n{bear.dissenting_risk}", style="italic dim")

    bull_panel = Panel(bull_text, border_style="green", expand=True)
    bear_panel = Panel(bear_text, border_style="red", expand=True)

    return Panel(
        Columns([bull_panel, bear_panel]),
        title="[bold]Adversarial Debate[/bold]",
        border_style="yellow",
    )


def _playbook_panel(playbook) -> Panel:
    """Render the ranked response playbook."""
    table = Table(show_header=True, header_style="bold white", expand=True)
    table.add_column("Pri", justify="center", width=4)
    table.add_column("Action", ratio=3)
    table.add_column("Timeframe", width=10)
    table.add_column("Conf", justify="right", width=6)
    table.add_column("Precedent", width=8)

    timeframe_colors = {
        "immediate": "bold red",
        "24h": "red",
        "72h": "yellow",
        "1-week": "green",
    }
    for action in playbook.actions:
        tf_color = timeframe_colors.get(action.timeframe, "white")
        cited = action.cited_precedent_id[:8] + "…" if action.cited_precedent_id else "—"
        table.add_row(
            str(action.priority),
            action.action[:80] + ("…" if len(action.action) > 80 else ""),
            f"[{tf_color}]{action.timeframe}[/{tf_color}]",
            f"{action.confidence:.0%}",
            cited,
        )

    dominant_color = "red" if "P10" in playbook.dominant_scenario else (
        "green" if "P90" in playbook.dominant_scenario else "yellow"
    )
    title = (
        f"[bold]Response Playbook[/bold] — "
        f"Dominant: [{dominant_color}]{playbook.dominant_scenario}[/{dominant_color}] | "
        f"Risk: [bold]{playbook.overall_risk.upper()}[/bold]"
    )
    return Panel(table, title=title, border_style="white")


def _quality_panel(ragas_score) -> Panel:
    """Render RAGAS evaluation scores."""
    if ragas_score is None:
        return Panel("[dim]RAGAS evaluation not available[/dim]", title="Quality Metrics", border_style="dim")

    table = Table(show_header=False, expand=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Weight", justify="right", style="dim")

    table.add_row("Faithfulness", f"{ragas_score.faithfulness:.3f}", "40%")
    table.add_row("Answer Relevance", f"{ragas_score.answer_relevance:.3f}", "30%")
    table.add_row("Context Precision", f"{ragas_score.context_precision:.3f}", "30%")
    table.add_row("─" * 15, "─" * 7, "─" * 5)

    overall_color = "green" if ragas_score.passed else "red"
    table.add_row(
        "[bold]Overall[/bold]",
        f"[{overall_color}]{ragas_score.overall:.3f}[/{overall_color}]",
        f"[{overall_color}]{'PASS' if ragas_score.passed else 'FAIL'}[/{overall_color}]",
    )
    return Panel(table, title="[bold]RAGAS Quality Metrics[/bold]", border_style="blue")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full SCDF 6-agent crew")
    parser.add_argument("--type", dest="disruption_type", default=None,
                        choices=["port", "weather", "tariff", "demand", "geopolitical"],
                        help="Force a specific disruption type")
    parser.add_argument("--severity", type=int, default=None, choices=range(1, 11),
                        metavar="1-10", help="Force a specific severity score")
    args = parser.parse_args()

    from src.agents.bear_analyst import run as run_bear
    from src.agents.bull_analyst import run as run_bull
    from src.agents.impact_modeler import run as run_impact_modeler
    from src.agents.playbook_writer import run as run_playbook_writer
    from src.agents.scenario_builder import run as run_scenario_builder
    from src.agents.signal_ingester import run as run_signal_ingester
    from src.signals.mock_generator import generate_mock_signal

    console.rule("[bold cyan]SCDF — Full 6-Agent Crew Run[/bold cyan]")
    signal = generate_mock_signal(
        disruption_type=args.disruption_type,
        severity=args.severity,
    )

    # ── Signal panel ──────────────────────────────────────────────────────────
    signal_text = Text()
    signal_text.append(f"ID:          {signal.signal_id}\n", style="dim")
    signal_text.append(f"Type:        {signal.disruption_type}\n")
    signal_text.append(f"Region:      {signal.region}\n")
    signal_text.append(f"Severity:    {signal.severity_score}/10\n")
    signal_text.append(f"Routes:      {', '.join(signal.affected_routes)}\n")
    signal_text.append(f"Source:      {signal.source}\n\n")
    signal_text.append(f"Description:\n{signal.description}", style="italic")
    console.print(Panel(signal_text, title="[bold]Disruption Signal[/bold]", border_style="red"))

    start = time.time()

    # ── Step 1: Signal ingestion ───────────────────────────────────────────────
    console.print("\n[bold cyan]▶ Step 1/6 — Signal Ingester (gpt-4o-mini)[/bold cyan]")
    signal_analysis = run_signal_ingester(signal)
    console.print(f"  Classified: {signal_analysis.disruption_type} | {signal_analysis.severity_label} | "
                  f"full crew: {signal_analysis.requires_full_crew}")

    # ── Step 2: Scenario building ──────────────────────────────────────────────
    console.print("[bold cyan]▶ Step 2/6 — Scenario Builder (Prophet)[/bold cyan]")
    scenario_set = run_scenario_builder(signal)
    console.print(_scenario_panel(scenario_set))

    # ── Step 3: Impact modeling ────────────────────────────────────────────────
    console.print("[bold cyan]▶ Step 3/6 — Impact Modeler (Qdrant RAG)[/bold cyan]")
    impact_analysis = run_impact_modeler(signal)
    console.print(_precedents_panel(impact_analysis))

    if signal_analysis.requires_full_crew:
        # ── Step 4 & 5: Bull + Bear debate ────────────────────────────────────
        console.print("[bold cyan]▶ Steps 4+5/6 — Bull + Bear Debate (gpt-4o, parallel)[/bold cyan]")
        import asyncio
        import threading

        bull_result: list = [None]
        bear_result: list = [None]

        def run_bull_thread():
            bull_result[0] = run_bull(signal, scenario_set, impact_analysis)

        def run_bear_thread():
            bear_result[0] = run_bear(signal, scenario_set, impact_analysis)

        t1 = threading.Thread(target=run_bull_thread)
        t2 = threading.Thread(target=run_bear_thread)
        t1.start(); t2.start()
        t1.join(); t2.join()

        bull_position = bull_result[0]
        bear_position = bear_result[0]
        console.print(_debate_panel(bull_position, bear_position))

        # ── Step 6: Playbook writer ────────────────────────────────────────────
        console.print("[bold cyan]▶ Step 6/6 — Playbook Writer (gpt-4o-mini)[/bold cyan]")
        playbook = run_playbook_writer(signal, scenario_set, impact_analysis, bull_position, bear_position)
    else:
        console.print(
            f"[yellow]Fast path — severity {signal.severity_score} < 4, skipping debate[/yellow]"
        )
        bull_position = None
        bear_position = None
        console.print("[bold cyan]▶ Step 6/6 — Playbook Writer (fast path)[/bold cyan]")
        playbook = run_playbook_writer(signal, scenario_set, impact_analysis)

    console.print(_playbook_panel(playbook))

    # ── RAGAS evaluation ───────────────────────────────────────────────────────
    try:
        from src.evaluation.ragas_scorer import evaluate_playbook
        ragas_score = evaluate_playbook(playbook, signal)
    except Exception as exc:
        console.print(f"[dim]RAGAS evaluation skipped: {exc}[/dim]")
        ragas_score = None

    console.print(_quality_panel(ragas_score))

    elapsed = time.time() - start
    console.rule(f"[bold green]Complete — {elapsed:.1f}s[/bold green]")


if __name__ == "__main__":
    main()
