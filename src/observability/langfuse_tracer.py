"""
Langfuse tracing for SCDF agent runs.

Uses the Langfuse 4.x SDK (OpenTelemetry-based).

Usage:
    # At the start of a crew run, create a top-level trace:
    trace_ctx = create_run_trace(signal_id="abc-123")

    # Decorate any agent function to produce a child span:
    @trace_agent("signal_ingester")
    def run(signal: DisruptionSignal) -> SignalAnalysis:
        ...
"""

import asyncio
import functools
import time
from contextvars import ContextVar
from typing import Any

from langfuse import Langfuse

from src.config.settings import get_settings

# Thread-local-like storage for the active trace context (safe across asyncio tasks)
_trace_context: ContextVar[dict | None] = ContextVar("langfuse_trace_context", default=None)

_tracer: Langfuse | None = None


def get_tracer() -> Langfuse:
    """Return the singleton Langfuse client, initialising it on first call."""
    global _tracer
    if _tracer is None:
        settings = get_settings()
        _tracer = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    return _tracer


def create_run_trace(signal_id: str) -> dict:
    """
    Create a top-level Langfuse trace for one full crew run.

    Sets the trace context in the current async task / thread so that all
    subsequent @trace_agent spans are automatically nested under it.

    Args:
        signal_id: The DisruptionSignal UUID — used as the trace seed for
                   deterministic, reproducible trace IDs.

    Returns:
        A trace context dict ({"trace_id": ...}) that can be passed to
        start_as_current_observation for explicit parent linking.
    """
    lf = get_tracer()
    trace_id = lf.create_trace_id(seed=signal_id)
    trace_ctx: dict = {"trace_id": trace_id}
    _trace_context.set(trace_ctx)
    return trace_ctx


def trace_agent(agent_name: str):
    """
    Decorator that wraps an agent function with a Langfuse span.

    Records input (first positional arg), output (return value), latency,
    and any exceptions. Works on both sync and async functions.

    Args:
        agent_name: Displayed span name in the Langfuse UI.
    """

    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await _run_with_trace(func, agent_name, args, kwargs, is_async=True)

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                return _run_with_trace_sync(func, agent_name, args, kwargs)

            return sync_wrapper

    return decorator


def _build_input(args: tuple) -> Any:
    """Extract a JSON-serialisable input dict from the first positional arg."""
    if not args:
        return {}
    first = args[0]
    if hasattr(first, "model_dump"):
        try:
            return first.model_dump(mode="json")
        except Exception:
            pass
    return {"input": str(first)[:500]}


def _build_output(result: Any) -> Any:
    """Convert a return value to a JSON-serialisable dict."""
    if result is None:
        return {}
    if hasattr(result, "model_dump"):
        try:
            return result.model_dump(mode="json")
        except Exception:
            pass
    return {"output": str(result)[:500]}


def _run_with_trace_sync(func, agent_name: str, args: tuple, kwargs: dict):
    lf = get_tracer()
    trace_ctx = _trace_context.get()
    start = time.monotonic()

    with lf.start_as_current_observation(
        name=agent_name,
        as_type="agent",
        trace_context=trace_ctx,
        input=_build_input(args),
        metadata={"agent": agent_name, "model": "stub", "week": 2},
    ):
        try:
            result = func(*args, **kwargs)
            lf.update_current_span(
                output=_build_output(result),
                metadata={
                    "agent": agent_name,
                    "model": "stub",
                    "week": 2,
                    "latency_ms": round((time.monotonic() - start) * 1000, 1),
                },
            )
            return result
        except Exception as exc:
            lf.update_current_span(
                output={"error": str(exc)},
                level="ERROR",
                status_message=str(exc),
            )
            raise


async def _run_with_trace(func, agent_name: str, args: tuple, kwargs: dict, is_async: bool):
    lf = get_tracer()
    trace_ctx = _trace_context.get()
    start = time.monotonic()

    with lf.start_as_current_observation(
        name=agent_name,
        as_type="agent",
        trace_context=trace_ctx,
        input=_build_input(args),
        metadata={"agent": agent_name, "model": "stub", "week": 2},
    ):
        try:
            result = await func(*args, **kwargs)
            lf.update_current_span(
                output=_build_output(result),
                metadata={
                    "agent": agent_name,
                    "model": "stub",
                    "week": 2,
                    "latency_ms": round((time.monotonic() - start) * 1000, 1),
                },
            )
            return result
        except Exception as exc:
            lf.update_current_span(
                output={"error": str(exc)},
                level="ERROR",
                status_message=str(exc),
            )
            raise
