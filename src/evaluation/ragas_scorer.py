"""
Manual RAGAS evaluation for SCDF playbook outputs.

Implements three core RAG quality metrics without the ragas pip package
(which pulls in heavy dependencies). Each metric is scored by gpt-4o-mini
via the Helicone proxy, and results are logged to Langfuse.

Metrics:
  faithfulness       — are playbook claims grounded in retrieved precedents?
  answer_relevance   — does the playbook address the disruption signal?
  context_precision  — were the right historical records retrieved?
"""

import json
import logging
from datetime import datetime, timezone

from pydantic import BaseModel

from src.config.helicone import get_openai_client
from src.models.outputs import Playbook
from src.signals.mock_generator import DisruptionSignal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

class RAGASScore(BaseModel):
    """RAGAS evaluation result for one crew run."""

    faithfulness: float       # 0.0–1.0: claims in answer supported by contexts
    answer_relevance: float   # 0.0–1.0: answer addresses the question/signal
    context_precision: float  # 0.0–1.0: retrieved passages are on-topic
    overall: float            # 0.4*F + 0.3*AR + 0.3*CP
    passed: bool              # True if overall >= 0.65
    evaluated_at: str         # ISO timestamp
    signal_id: str


# ---------------------------------------------------------------------------
# Individual scorers
# ---------------------------------------------------------------------------

def _call_llm(prompt: str) -> float:
    """
    Send a scoring prompt to gpt-4o-mini via Helicone and parse the score float.

    Returns 0.5 on any parse error (neutral score with warning logged).
    """
    client = get_openai_client(agent_name="ragas-scorer")
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=120,
        )
        raw = resp.choices[0].message.content.strip()
        # Extract JSON even if there's surrounding text
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
            score = float(data.get("score", 0.5))
            return max(0.0, min(1.0, score))
        logger.warning(f"No JSON found in LLM response: {raw[:200]}")
        return 0.5
    except Exception as exc:
        logger.warning(f"RAGAS LLM call failed: {exc}")
        return 0.5


def score_faithfulness(answer: str, contexts: list[str]) -> float:
    """
    Rate how faithfully the answer's claims are grounded in the retrieved contexts.

    Score 1.0 = every claim traceable to a context passage.
    Score 0.0 = answer is completely unsupported by contexts.
    """
    context_block = "\n\n".join(f"[Context {i+1}]: {c}" for i, c in enumerate(contexts))
    prompt = f"""You are a supply chain RAG evaluation expert.

Retrieved context passages:
{context_block}

Answer/playbook to evaluate:
{answer}

Task: Rate on a scale of 0.0 to 1.0 how faithfully the answer is grounded in the context passages.
A score of 1.0 means every claim in the answer can be traced to a context passage.
A score of 0.0 means the answer makes claims not supported by any context.

Respond with ONLY a JSON object: {{"score": <float>, "reasoning": "<one sentence>"}}"""
    return _call_llm(prompt)


def score_answer_relevance(question: str, answer: str) -> float:
    """
    Rate how relevant and actionable the playbook is for the disruption signal.

    Score 1.0 = answer directly addresses the disruption with specific actions.
    Score 0.0 = answer is generic or unrelated to the signal.
    """
    prompt = f"""You are a supply chain operations evaluator.

Disruption signal/question:
{question}

Response playbook action:
{answer}

Task: Rate on a scale of 0.0 to 1.0 how relevant and actionable this response is for the specific disruption signal.
A score of 1.0 means the response directly addresses this exact type of disruption with specific, executable actions.
A score of 0.0 means the response is generic or irrelevant.

Respond with ONLY a JSON object: {{"score": <float>, "reasoning": "<one sentence>"}}"""
    return _call_llm(prompt)


def score_context_precision(query: str, contexts: list[str]) -> float:
    """
    Rate whether the right historical disruption records were retrieved.

    Score 1.0 = all retrieved passages are highly relevant to the query.
    Score 0.0 = retrieved passages are unrelated to the disruption type/region.
    """
    context_block = "\n\n".join(f"[Context {i+1}]: {c}" for i, c in enumerate(contexts))
    prompt = f"""You are a supply chain RAG retrieval evaluator.

Disruption query:
{query}

Retrieved historical precedent passages:
{context_block}

Task: Rate on a scale of 0.0 to 1.0 how precisely relevant these retrieved passages are to the query.
A score of 1.0 means all passages are highly relevant historical precedents for this exact disruption type.
A score of 0.0 means the passages are off-topic or irrelevant.

Respond with ONLY a JSON object: {{"score": <float>, "reasoning": "<one sentence>"}}"""
    return _call_llm(prompt)


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate_playbook(playbook: Playbook, signal: DisruptionSignal) -> RAGASScore:
    """
    Score a playbook on all three RAGAS metrics and log results to Langfuse.

    Uses:
      - playbook.ragas_context as the retrieved contexts
      - signal.description as the question
      - The first action's action + rationale as the answer to evaluate

    Returns:
        RAGASScore with all metrics, overall score, and pass/fail judgment.
    """
    contexts = playbook.ragas_context
    question = signal.description

    # Answer = top-priority action + its rationale
    if playbook.actions:
        top_action = playbook.actions[0]
        answer = f"{top_action.action} — {top_action.rationale}"
    else:
        answer = "No actions generated."

    # Score all three metrics
    faithfulness = score_faithfulness(answer=answer, contexts=contexts)
    answer_rel = score_answer_relevance(question=question, answer=answer)
    ctx_prec = score_context_precision(query=question, contexts=contexts)

    # Weighted overall
    overall = round(0.4 * faithfulness + 0.3 * answer_rel + 0.3 * ctx_prec, 4)

    score = RAGASScore(
        faithfulness=round(faithfulness, 4),
        answer_relevance=round(answer_rel, 4),
        context_precision=round(ctx_prec, 4),
        overall=overall,
        passed=overall >= 0.65,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        signal_id=signal.signal_id,
    )

    # Log to Langfuse as a score event on the active trace
    try:
        from src.observability.langfuse_tracer import get_tracer, _trace_context
        lf = get_tracer()
        trace_ctx = _trace_context.get()
        if trace_ctx:
            trace_id = trace_ctx.get("trace_id")
            if trace_id:
                lf.score_current_trace(
                    name="ragas_overall",
                    value=overall,
                    comment=f"faithfulness={faithfulness:.3f} relevance={answer_rel:.3f} precision={ctx_prec:.3f}",
                )
    except Exception as exc:
        logger.debug(f"Langfuse score logging skipped: {exc}")

    return score
