"""
Publish mock disruption signals to the Upstash Redis stream.

Usage:
    python -m scripts.publish_signal
    python -m scripts.publish_signal --type tariff --severity 6 --count 3
    python -m scripts.publish_signal --type port --severity 8 --region Asia-Pacific
"""

import argparse
import sys

from rich.console import Console
from rich.table import Table

from src.ingestion.redis_consumer import publish_signal
from src.signals.mock_generator import generate_mock_signal

console = Console()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish mock disruption signals to the SCDF Redis stream."
    )
    parser.add_argument(
        "--type",
        dest="disruption_type",
        default="port",
        choices=["port", "weather", "tariff", "demand", "geopolitical"],
        help="Disruption type to generate (default: port)",
    )
    parser.add_argument(
        "--severity",
        type=int,
        default=7,
        metavar="1-10",
        help="Severity score 1-10 (default: 7)",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="Override region (default: template default)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of signals to publish (default: 1)",
    )
    args = parser.parse_args()

    table = Table(title="Published Signals", show_header=True, header_style="bold blue")
    table.add_column("Signal ID", style="cyan", min_width=36)
    table.add_column("Type", style="magenta")
    table.add_column("Region", style="green")
    table.add_column("Severity", justify="center")
    table.add_column("Stream Entry ID", style="dim")

    console.rule("[bold cyan]SCDF Signal Publisher[/bold cyan]")

    try:
        for _ in range(args.count):
            signal = generate_mock_signal(
                disruption_type=args.disruption_type,
                severity=args.severity,
            )
            # Override region if explicitly specified
            if args.region:
                signal = signal.model_copy(update={"region": args.region})

            entry_id = publish_signal(signal)
            table.add_row(
                signal.signal_id,
                signal.disruption_type,
                signal.region,
                str(signal.severity_score),
                str(entry_id),
            )
    except RuntimeError as exc:
        console.print(f"[red]Redis error: {exc}[/red]")
        console.print("Ensure UPSTASH_REDIS_URL is set in .env")
        return 1

    console.print(table)
    console.print(f"\n[green]✓ Published {args.count} signal(s) to stream 'scdf:signals'[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
