"""
Prompt tuning toolkit — iterates on debate and playbook prompts, reports quality.

Modes:
  debate    — run N debate iterations, show confidence gaps and scenario agreement
  playbook  — run N playbook iterations, show action quality metrics
  validate  — run debate quality validation with pass/fail report

Usage:
    python -m scripts.tune_prompts --mode debate --runs 5
    python -m scripts.tune_prompts --mode playbook --runs 3
    python -m scripts.tune_prompts --mode validate --runs 5
"""

import argparse
import logging
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
logging.basicConfig(level=logging.WARNING)


def _run_debate_mode(n_runs: int) -> None:
    """Run N debate iterations and show per-run results."""
    from src.agents.bear_analyst import run as run_bear
    from src.agents.bull_analyst import run as run_bull
    from src.agents.impact_modeler import run as run_impact_modeler
    from src.agents.scenario_builder import run as run_scenario_builder
    from src.signals.mock_generator import generate_mock_signal

    console.print(f"\n[bold cyan]Debate tuning — {n_runs} runs[/bold cyan]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Run", width=4)
    table.add_column("Bull conf", justify="right")
    table.add_column("Bull rec")
    table.add_column("Bear conf", justify="right")
    table.add_column("Bear rec")
    table.add_column("Gap", justify="right")
    table.add_column("Agree?")

    gaps = []
    agreements = []

    for i in range(n_runs):
        try:
            signal = generate_mock_signal(disruption_type="port", severity=8)
            scenario_set = run_scenario_builder(signal)
            impact_analysis = run_impact_modeler(signal)
            bull = run_bull(signal, scenario_set, impact_analysis)
            bear = run_bear(signal, scenario_set, impact_analysis)

            gap = abs(bull.confidence - bear.confidence)
            agree = bull.recommended_scenario == bear.recommended_scenario
            gaps.append(gap)
            agreements.append(agree)

            agree_str = "[red]YES[/red]" if agree else "[green]NO[/green]"
            gap_color = "green" if gap > 0.10 else "red"
            table.add_row(
                str(i + 1),
                f"{bull.confidence:.2f}",
                bull.recommended_scenario,
                f"{bear.confidence:.2f}",
                bear.recommended_scenario,
                f"[{gap_color}]{gap:.2f}[/{gap_color}]",
                agree_str,
            )
        except Exception as exc:
            table.add_row(str(i + 1), "ERR", "—", "ERR", "—", "—", f"[red]{exc}[/red]")

    console.print(table)

    if gaps:
        avg_gap = sum(gaps) / len(gaps)
        agree_rate = sum(agreements) / len(agreements)
        gap_ok = avg_gap > 0.10
        agree_ok = agree_rate < 0.40
        summary = (
            f"Avg gap: [{'green' if gap_ok else 'red'}]{avg_gap:.3f}[/] (need > 0.10)  |  "
            f"Agreement rate: [{'green' if agree_ok else 'red'}]{agree_rate:.0%}[/] (need < 40%)  |  "
            f"Overall: [{'bold green' if gap_ok and agree_ok else 'bold red'}]"
            f"{'PASS' if gap_ok and agree_ok else 'FAIL'}[/]"
        )
        console.print(Panel(summary, title="Summary", expand=False))


def _run_playbook_mode(n_runs: int) -> None:
    """Run N playbook iterations and show action diversity metrics."""
    from src.agents.bear_analyst import run as run_bear
    from src.agents.bull_analyst import run as run_bull
    from src.agents.impact_modeler import run as run_impact_modeler
    from src.agents.playbook_writer import run as run_playbook_writer
    from src.agents.scenario_builder import run as run_scenario_builder
    from src.signals.mock_generator import generate_mock_signal

    console.print(f"\n[bold cyan]Playbook tuning — {n_runs} runs[/bold cyan]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Run", width=4)
    table.add_column("Dominant")
    table.add_column("Actions", justify="right")
    table.add_column("Cited", justify="right")
    table.add_column("Avg conf", justify="right")
    table.add_column("RAGAS")

    for i in range(n_runs):
        try:
            signal = generate_mock_signal(disruption_type="port", severity=8)
            scenario_set = run_scenario_builder(signal)
            impact_analysis = run_impact_modeler(signal)
            bull = run_bull(signal, scenario_set, impact_analysis)
            bear = run_bear(signal, scenario_set, impact_analysis)
            playbook = run_playbook_writer(signal, scenario_set, impact_analysis, bull, bear)

            cited_count = sum(1 for a in playbook.actions if a.cited_precedent_id)
            avg_conf = sum(a.confidence for a in playbook.actions) / len(playbook.actions)

            try:
                from src.evaluation.ragas_scorer import evaluate_playbook
                ragas = evaluate_playbook(playbook, signal)
                ragas_str = f"{'✓' if ragas.passed else '✗'} {ragas.overall:.2f}"
            except Exception:
                ragas_str = "—"

            table.add_row(
                str(i + 1),
                playbook.dominant_scenario[:20],
                str(len(playbook.actions)),
                str(cited_count),
                f"{avg_conf:.2f}",
                ragas_str,
            )
        except Exception as exc:
            table.add_row(str(i + 1), "ERR", "—", "—", "—", f"[red]{exc}[/red]")

    console.print(table)


def _run_validate_mode(n_runs: int) -> None:
    """Run the full debate quality validation report."""
    from src.prompts.prompt_validator import run_validation_report
    run_validation_report(n_runs)


def main() -> None:
    parser = argparse.ArgumentParser(description="SCDF prompt tuning toolkit")
    parser.add_argument(
        "--mode", choices=["debate", "playbook", "validate"], default="validate",
        help="Tuning mode (default: validate)",
    )
    parser.add_argument(
        "--runs", type=int, default=5,
        help="Number of iterations to run (default: 5)",
    )
    args = parser.parse_args()

    if args.mode == "debate":
        _run_debate_mode(args.runs)
    elif args.mode == "playbook":
        _run_playbook_mode(args.runs)
    else:
        _run_validate_mode(args.runs)


if __name__ == "__main__":
    main()
