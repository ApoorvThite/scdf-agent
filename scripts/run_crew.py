"""
Run the SCDF disruption crew end-to-end and print results.

Usage:
    python -m scripts.run_crew
    python -m scripts.run_crew --type port --severity 8
    python -m scripts.run_crew --type weather --severity 2
"""

import argparse
import json
import time

from rich.console import Console
from rich.json import JSON
from rich.rule import Rule

from src.flows.disruption_flow import run
from src.observability.langfuse_tracer import get_tracer
from src.signals.mock_generator import generate_mock_signal

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Run the SCDF disruption crew")
    parser.add_argument(
        "--type",
        dest="disruption_type",
        default=None,
        choices=["weather", "port", "tariff", "demand", "geopolitical"],
        help="Force a specific disruption type",
    )
    parser.add_argument(
        "--severity",
        type=int,
        default=None,
        choices=range(1, 11),
        metavar="1-10",
        help="Force a specific severity score (1-10)",
    )
    args = parser.parse_args()

    # 1. Generate signal
    signal = generate_mock_signal(
        disruption_type=args.disruption_type,
        severity=args.severity,
    )

    console.print(Rule("[bold cyan]SCDF Disruption Signal[/bold cyan]"))
    console.print(JSON(json.dumps(signal.model_dump(mode="json"), default=str)))

    # 2. Run crew
    console.print(Rule("[bold yellow]Running Crew...[/bold yellow]"))
    start_time = time.monotonic()

    playbook = run(signal)

    elapsed = time.monotonic() - start_time

    # 3. Print playbook
    console.print(Rule("[bold green]Playbook Output[/bold green]"))
    console.print(JSON(json.dumps(playbook.model_dump(mode="json"), default=str)))

    # 4. Summary line
    fast = signal.severity_score < 4
    path = "fast-path" if fast else "full-debate"
    agents_run = 4 if fast else 6

    lf = get_tracer()
    trace_url = f"{lf._client_wrapper._base_url}/traces" if hasattr(lf, "_client_wrapper") else "http://localhost:3000/traces"  # noqa

    console.print(Rule("[bold blue]Summary[/bold blue]"))
    console.print(
        f"  Agents run:   [bold]{agents_run}[/bold] ({path})\n"
        f"  Total time:   [bold]{elapsed:.2f}s[/bold]\n"
        f"  Risk level:   [bold red]{playbook.overall_risk}[/bold red]\n"
        f"  Langfuse URL: {trace_url}"
    )


if __name__ == "__main__":
    main()
