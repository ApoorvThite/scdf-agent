"""
RAGAS evaluation runner — runs the full SCDF crew on multiple signal types
and evaluates each resulting playbook against three RAG quality metrics.

Usage:
    python -m scripts.evaluate_playbook

Output:
    Rich table of RAGAS scores per signal
    JSON results saved to data/eval_results/week3_ragas_{timestamp}.json
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console
from rich.table import Table

from src.evaluation.ragas_scorer import evaluate_playbook
from src.flows.disruption_flow import run as run_flow
from src.signals.mock_generator import generate_mock_signal

console = Console()

EVAL_SIGNALS = [
    {"disruption_type": "port", "severity": 8},
    {"disruption_type": "weather", "severity": 6},
    {"disruption_type": "tariff", "severity": 5},
]


def _format_score(v: float, threshold: float = 0.65) -> str:
    colour = "green" if v >= threshold else "red"
    return f"[{colour}]{v:.2f}[/{colour}]"


def main():
    console.rule("[bold cyan]SCDF RAGAS Playbook Evaluation[/bold cyan]")

    results = []
    table = Table(title="RAGAS Evaluation Results", show_header=True, header_style="bold blue")
    table.add_column("Signal", style="cyan", min_width=20)
    table.add_column("Faithfulness", justify="center")
    table.add_column("Answer Relevance", justify="center")
    table.add_column("Context Precision", justify="center")
    table.add_column("Overall", justify="center")
    table.add_column("Passed", justify="center")

    for sig_params in EVAL_SIGNALS:
        signal = generate_mock_signal(**sig_params)
        label = f"{sig_params['disruption_type']} / {signal.region[:6]} / {sig_params['severity']}"
        console.print(f"\nRunning crew for: [bold]{label}[/bold]  signal_id={signal.signal_id}")

        start = time.monotonic()

        # Mock Langfuse to avoid requiring a live server during evaluation
        mock_lf = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_lf.start_as_current_observation.return_value = mock_cm
        mock_lf.create_trace_id.return_value = "mock-trace-id"

        with patch("src.observability.langfuse_tracer.get_tracer", return_value=mock_lf):
            try:
                playbook = run_flow(signal)
                ragas = evaluate_playbook(playbook, signal)
            except Exception as exc:
                console.print(f"  [red]Error: {exc}[/red]")
                continue

        elapsed = time.monotonic() - start
        console.print(
            f"  Crew completed in {elapsed:.1f}s  "
            f"risk={playbook.overall_risk}  "
            f"ragas_overall={ragas.overall:.3f}"
        )

        table.add_row(
            label,
            _format_score(ragas.faithfulness),
            _format_score(ragas.answer_relevance),
            _format_score(ragas.context_precision),
            _format_score(ragas.overall),
            "[green]✓[/green]" if ragas.passed else "[red]✗[/red]",
        )

        results.append({
            "signal": sig_params,
            "signal_id": signal.signal_id,
            "region": signal.region,
            "playbook_risk": playbook.overall_risk,
            "faithfulness": ragas.faithfulness,
            "answer_relevance": ragas.answer_relevance,
            "context_precision": ragas.context_precision,
            "overall": ragas.overall,
            "passed": ragas.passed,
        })

    console.print()
    console.print(table)

    # Summary
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    console.print(f"\n[bold]{passed}/{total}[/bold] playbooks passed RAGAS threshold (>=0.65)")

    # Save JSON results
    out_dir = Path("data/eval_results")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"week3_ragas_{ts}.json"
    out_path.write_text(json.dumps({
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "summary": {"passed": passed, "total": total},
    }, indent=2))
    console.print(f"Results saved to [bold]{out_path}[/bold]")

    return 0 if passed >= 1 else 1


if __name__ == "__main__":
    sys.exit(main())
