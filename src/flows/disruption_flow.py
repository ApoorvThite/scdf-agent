"""
DisruptionFlow — deterministic CrewAI Flow backbone for SCDF.

Execution paths:
  FULL DEBATE  (severity >= 4):
    ingest_signal → build_scenarios → model_impact
    → [bull + bear in parallel] → write_playbook → persist_result

  FAST PATH    (severity < 4):
    ingest_signal → build_scenarios → model_impact
    → fast_playbook → persist_result

persist_result saves to DynamoDB and publishes SNS alerts in addition to RAGAS
evaluation. All I/O is wrapped in try/except — infra failures never crash the crew.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level flag: ensures ensure_table_exists() runs only once per process
_startup_done = False

from crewai.flow.flow import Flow, listen, router, start, or_
from pydantic import BaseModel, Field

from src.agents.bear_analyst import run as run_bear
from src.agents.bull_analyst import run as run_bull
from src.agents.impact_modeler import run as run_impact_modeler
from src.agents.playbook_writer import run as run_playbook_writer
from src.agents.scenario_builder import run as run_scenario_builder
from src.agents.signal_ingester import run as run_signal_ingester
from src.models.outputs import (
    AnalystPosition,
    ImpactAnalysis,
    Playbook,
    ScenarioSet,
    SignalAnalysis,
)
from src.evaluation.ragas_scorer import RAGASScore
from src.observability.langfuse_tracer import create_run_trace, get_tracer
from src.signals.mock_generator import DisruptionSignal

_FAST_PATH = "fast_path"
_FULL_DEBATE = "full_debate"


def startup_check() -> None:
    """
    One-time startup routine: ensure DynamoDB table exists.

    Guarded by _startup_done flag so it runs at most once per process,
    at the beginning of the first ingest_signal call.
    Logs success/failure but never raises — infra issues must not block signal processing.
    """
    global _startup_done
    if _startup_done:
        return
    _startup_done = True
    try:
        from src.persistence.dynamodb import ensure_table_exists
        ensure_table_exists()
        logger.info("[startup] DynamoDB table ready")
    except Exception as exc:
        logger.warning(f"[startup] DynamoDB setup failed (continuing): {exc}")


class FlowState(BaseModel):
    signal: Optional[DisruptionSignal] = None
    signal_analysis: Optional[SignalAnalysis] = None
    scenario_set: Optional[ScenarioSet] = None
    impact_analysis: Optional[ImpactAnalysis] = None
    bull_position: Optional[AnalystPosition] = None
    bear_position: Optional[AnalystPosition] = None
    playbook: Optional[Playbook] = None
    ragas_score: Optional[RAGASScore] = None
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str] = None
    fast_path: bool = False


class DisruptionFlow(Flow[FlowState]):
    """
    CrewAI Flow that orchestrates the 6-agent SCDF crew.

    State flows through sequential steps with a router that branches
    low-severity signals to a fast path (skipping the debate crew).
    """

    @start()
    def ingest_signal(self):
        """Classify the raw signal and determine routing."""
        assert self.state.signal is not None, "signal must be set before kickoff"
        startup_check()
        create_run_trace(signal_id=self.state.signal.signal_id)

        analysis = run_signal_ingester(self.state.signal)
        self.state.signal_analysis = analysis

        if not analysis.requires_full_crew:
            self.state.fast_path = True

    @listen(ingest_signal)
    def build_scenarios(self):
        """Generate P10/P50/P90 scenario narratives."""
        self.state.scenario_set = run_scenario_builder(self.state.signal)

    @listen(build_scenarios)
    def model_impact(self):
        """Retrieve historical precedents and estimate KPI impacts."""
        self.state.impact_analysis = run_impact_modeler(self.state.signal)

    @router(model_impact)
    def route_after_impact(self) -> str:
        """Branch to fast path for low-severity signals; full debate otherwise."""
        if self.state.fast_path:
            return _FAST_PATH
        return _FULL_DEBATE

    @listen(_FULL_DEBATE)
    async def run_debate(self):
        """Run bull and bear analysts in parallel using asyncio.gather."""
        bull_result, bear_result = await asyncio.gather(
            asyncio.to_thread(run_bull, self.state.signal),
            asyncio.to_thread(run_bear, self.state.signal),
        )
        self.state.bull_position = bull_result
        self.state.bear_position = bear_result

    @listen(_FAST_PATH)
    def fast_playbook(self):
        """Fast path — skip debate and write playbook directly from P50 scenario."""
        self.state.playbook = run_playbook_writer(self.state.signal)
        self.state.completed_at = datetime.now(timezone.utc).isoformat()

    @listen(run_debate)
    def write_playbook(self):
        """Synthesise debate outputs into the final ranked playbook."""
        self.state.playbook = run_playbook_writer(self.state.signal)
        self.state.completed_at = datetime.now(timezone.utc).isoformat()

    @listen(write_playbook)
    @listen(fast_playbook)
    def persist_result(self):
        """
        Final step: evaluate quality, persist to DynamoDB, and notify planners.

        All I/O is wrapped in try/except — infra failures never crash the crew.
        Execution order:
          1. RAGAS quality evaluation (gpt-4o-mini judge)
          2. DynamoDB upsert (full FlowState serialisation)
          3. SNS alert routing (risk-based topic selection)
          4. Langfuse flush (ensures all spans are recorded)
        """
        playbook = self.state.playbook
        assert playbook is not None

        # 1. RAGAS quality evaluation
        try:
            from src.evaluation.ragas_scorer import evaluate_playbook
            ragas_score = evaluate_playbook(playbook, self.state.signal)
            self.state.ragas_score = ragas_score
            logger.info(
                f"[ragas] overall={ragas_score.overall:.3f} "
                f"faithfulness={ragas_score.faithfulness:.3f} "
                f"relevance={ragas_score.answer_relevance:.3f} "
                f"precision={ragas_score.context_precision:.3f} "
                f"passed={'✓' if ragas_score.passed else '✗'}"
            )
        except Exception as exc:
            logger.warning(f"[ragas] evaluation skipped: {exc}")

        # 2. DynamoDB persistence — save full FlowState
        try:
            from src.persistence.dynamodb import save_playbook_result
            saved = save_playbook_result(self.state)
            if not saved:
                logger.warning(
                    f"[dynamodb] save returned False for {self.state.signal.signal_id}"
                )
        except Exception as exc:
            logger.error(f"[dynamodb] error: {exc}")

        # 3. SNS notification routing
        try:
            from src.notifications.sns_publisher import publish_playbook_alert
            publish_playbook_alert(playbook, self.state.ragas_score)
        except Exception as exc:
            logger.error(f"[sns] error: {exc}")

        # 4. Flush Langfuse so all agent spans and scores are recorded
        try:
            get_tracer().flush()
        except Exception:
            pass

        self.state.completed_at = datetime.now(timezone.utc).isoformat()
        return playbook


def run(signal: DisruptionSignal) -> Playbook:
    """
    Convenience function: create a flow instance, kick it off, return the Playbook.

    Args:
        signal: The DisruptionSignal to process.

    Returns:
        The completed Playbook produced by the crew.
    """
    flow = DisruptionFlow()
    flow.state.signal = signal
    flow.state.run_id = str(uuid.uuid4())
    flow.state.started_at = datetime.now(timezone.utc).isoformat()
    result = flow.kickoff()
    return result
