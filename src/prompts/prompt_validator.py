"""
Debate quality validator — runs N debate iterations and measures disagreement.

Used to ensure that the bull and bear prompts produce genuinely different
positions. If the agents converge (same recommended_scenario, small confidence
gap), the prompts need tuning.

Metrics:
  avg_confidence_gap      — mean |bull.confidence - bear.confidence| across runs
  scenario_agreement_rate — fraction of runs where both analysts recommend same scenario
  passed                  — True when gap > 0.10 AND agreement_rate < 0.40
"""

import logging
from typing import Optional

from pydantic import BaseModel

from src.models.outputs import AnalystPosition

logger = logging.getLogger(__name__)


class DebateQualityReport(BaseModel):
    """Results of a debate quality validation run."""

    n_runs: int
    avg_confidence_gap: float
    scenario_agreement_rate: float
    bull_avg_confidence: float
    bear_avg_confidence: float
    passed: bool
    failure_reason: Optional[str] = None


def validate_debate_quality(n_runs: int = 5) -> DebateQualityReport:
    """
    Run N debate iterations on a representative signal and measure disagreement.

    Generates a fresh high-severity port disruption signal for each run,
    calls the full bull + bear pipeline, and computes divergence metrics.

    Args:
        n_runs: Number of debate iterations to run (default 5, use 1 for quick check).

    Returns:
        A DebateQualityReport with pass/fail and diagnostic metrics.
    """
    from src.agents.bear_analyst import run as run_bear
    from src.agents.bull_analyst import run as run_bull
    from src.agents.impact_modeler import run as run_impact_modeler
    from src.agents.scenario_builder import run as run_scenario_builder
    from src.agents.signal_ingester import run as run_signal_ingester
    from src.signals.mock_generator import generate_mock_signal

    confidence_gaps: list[float] = []
    scenario_agreements: list[bool] = []
    bull_confidences: list[float] = []
    bear_confidences: list[float] = []

    for i in range(n_runs):
        try:
            # Use port/severity-8 for a consistent high-stakes scenario
            signal = generate_mock_signal(disruption_type="port", severity=8)
            scenario_set = run_scenario_builder(signal)
            impact_analysis = run_impact_modeler(signal)

            bull: AnalystPosition = run_bull(signal, scenario_set, impact_analysis)
            bear: AnalystPosition = run_bear(signal, scenario_set, impact_analysis)

            gap = abs(bull.confidence - bear.confidence)
            agree = bull.recommended_scenario == bear.recommended_scenario

            confidence_gaps.append(gap)
            scenario_agreements.append(agree)
            bull_confidences.append(bull.confidence)
            bear_confidences.append(bear.confidence)

            logger.info(
                f"[validate_debate] run {i+1}/{n_runs}: "
                f"bull={bull.confidence:.2f} ({bull.recommended_scenario}), "
                f"bear={bear.confidence:.2f} ({bear.recommended_scenario}), "
                f"gap={gap:.2f}, agree={agree}"
            )

        except Exception as exc:
            logger.warning(f"[validate_debate] run {i+1} failed: {exc}")
            # Count failed runs as neutral (no gap, no agreement) to be conservative
            confidence_gaps.append(0.0)
            scenario_agreements.append(True)
            bull_confidences.append(0.5)
            bear_confidences.append(0.5)

    avg_gap = sum(confidence_gaps) / len(confidence_gaps) if confidence_gaps else 0.0
    agreement_rate = sum(scenario_agreements) / len(scenario_agreements) if scenario_agreements else 1.0
    bull_avg = sum(bull_confidences) / len(bull_confidences) if bull_confidences else 0.5
    bear_avg = sum(bear_confidences) / len(bear_confidences) if bear_confidences else 0.5

    passed = avg_gap > 0.10 and agreement_rate < 0.40
    failure_reason = None
    if not passed:
        reasons = []
        if avg_gap <= 0.10:
            reasons.append(f"confidence gap too small ({avg_gap:.2f} ≤ 0.10)")
        if agreement_rate >= 0.40:
            reasons.append(f"scenario agreement rate too high ({agreement_rate:.0%} ≥ 40%)")
        failure_reason = "; ".join(reasons)

    return DebateQualityReport(
        n_runs=n_runs,
        avg_confidence_gap=round(avg_gap, 3),
        scenario_agreement_rate=round(agreement_rate, 3),
        bull_avg_confidence=round(bull_avg, 3),
        bear_avg_confidence=round(bear_avg, 3),
        passed=passed,
        failure_reason=failure_reason,
    )


def run_validation_report(n_runs: int = 5) -> None:
    """
    Run debate quality validation and print a Rich-formatted report.

    Args:
        n_runs: Number of debate iterations to run.
    """
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        console = Console()
    except ImportError:
        # Fall back to plain logging if Rich is unavailable
        report = validate_debate_quality(n_runs)
        logger.info(f"Debate quality report: {report.model_dump()}")
        return

    console.print(f"\n[bold cyan]Running debate quality validation ({n_runs} runs)...[/bold cyan]\n")
    report = validate_debate_quality(n_runs)

    table = Table(title="Debate Quality Report", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")
    table.add_column("Threshold", style="dim")
    table.add_column("Status", style="bold")

    def status(ok: bool) -> str:
        return "[green]PASS[/green]" if ok else "[red]FAIL[/red]"

    table.add_row("Runs completed", str(report.n_runs), "—", "")
    table.add_row(
        "Avg confidence gap",
        f"{report.avg_confidence_gap:.3f}",
        "> 0.10",
        status(report.avg_confidence_gap > 0.10),
    )
    table.add_row(
        "Scenario agreement rate",
        f"{report.scenario_agreement_rate:.1%}",
        "< 40%",
        status(report.scenario_agreement_rate < 0.40),
    )
    table.add_row("Bull avg confidence", f"{report.bull_avg_confidence:.3f}", "—", "")
    table.add_row("Bear avg confidence", f"{report.bear_avg_confidence:.3f}", "—", "")

    console.print(table)

    verdict = "[bold green]PASSED[/bold green]" if report.passed else "[bold red]FAILED[/bold red]"
    summary = f"Overall: {verdict}"
    if report.failure_reason:
        summary += f"\nReason: {report.failure_reason}"
    console.print(Panel(summary, title="Validation Result", expand=False))
