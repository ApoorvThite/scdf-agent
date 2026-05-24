"""
SCDF ingestion layer — Redis Streams signal bus.

Provides publish/consume functions for the Upstash Redis Streams signal bus.
"""

from src.ingestion.redis_consumer import publish_signal, consume_signals, consume_once

__all__ = ["publish_signal", "consume_signals", "consume_once"]
