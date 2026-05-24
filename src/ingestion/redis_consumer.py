"""
Upstash Redis Streams consumer for the SCDF signal bus.

Signals are published by mock_generator, the Lambda trigger, or the CLI tool
and consumed here for dispatch to the CrewAI DisruptionFlow.

Stream architecture:
  Producer: publish_signal() → XADD scdf:signals
  Consumer: consume_signals() → XREADGROUP → handler(signal) → XACK

Consumer group semantics:
  - Each consumed message is delivered to exactly one worker in the group
  - Unacknowledged messages stay pending and are redelivered on reconnect
  - XACK is called only after the handler succeeds

Run as a standalone process:
    python -m src.ingestion.redis_consumer
"""

import json
import logging
import time
from typing import Callable

import redis
from redis.exceptions import ResponseError

from src.config.settings import get_settings
from src.signals.mock_generator import DisruptionSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stream constants
# ---------------------------------------------------------------------------

STREAM_KEY = "scdf:signals"
CONSUMER_GROUP = "scdf-crew"
CONSUMER_NAME = "worker-1"

# Maximum number of messages to read per XREADGROUP call
_DEFAULT_BATCH = 1
# Milliseconds to block waiting for new messages (5 s)
_DEFAULT_BLOCK_MS = 5000


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def get_redis_client() -> redis.Redis:
    """
    Create an Upstash Redis client using UPSTASH_REDIS_URL from settings.

    Upstash URLs use the rediss:// scheme (SSL) and embed credentials.
    The client is validated with a PING before being returned.

    Returns:
        A connected redis.Redis instance with decode_responses=True.

    Raises:
        RuntimeError: if UPSTASH_REDIS_URL is not configured or connection fails.
    """
    settings = get_settings()
    url = settings.upstash_redis_url
    if not url:
        raise RuntimeError(
            "UPSTASH_REDIS_URL is not configured. "
            "Add it to .env or set the environment variable."
        )
    try:
        # from_url auto-detects rediss:// and enables SSL
        client = redis.Redis.from_url(url, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:
        logger.error(f"Redis connection failed: {exc}")
        raise RuntimeError(f"Failed to connect to Redis: {exc}") from exc


# ---------------------------------------------------------------------------
# Stream lifecycle helpers
# ---------------------------------------------------------------------------

def ensure_stream_and_group(client: redis.Redis) -> None:
    """
    Create the SCDF stream and consumer group if they do not already exist.

    MKSTREAM creates the stream atomically if it doesn't exist. Safe to call
    on every startup — BUSYGROUP error is silently ignored.

    Args:
        client: Connected redis.Redis instance.
    """
    try:
        # $ means start reading from new entries only (not backlog)
        client.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="$", mkstream=True)
        logger.info(f"Created consumer group '{CONSUMER_GROUP}' on stream '{STREAM_KEY}'")
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            # Group already exists — this is the normal case after first startup
            logger.debug(f"Consumer group '{CONSUMER_GROUP}' already exists")
        else:
            raise


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------

def publish_signal(signal: DisruptionSignal) -> str:
    """
    Serialise a DisruptionSignal to JSON and publish it to the Redis stream.

    Args:
        signal: The DisruptionSignal to publish.

    Returns:
        The stream entry ID assigned by Redis (e.g. "1700000000000-0").
    """
    client = get_redis_client()
    payload = json.dumps(signal.model_dump(mode="json"), default=str)
    # XADD with * lets Redis assign the ID automatically
    entry_id = client.xadd(STREAM_KEY, {"data": payload})
    logger.info(f"Published signal {signal.signal_id} → stream entry {entry_id}")
    return entry_id


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------

def _parse_message(message: dict) -> DisruptionSignal | None:
    """Deserialise a Redis stream message dict into a DisruptionSignal."""
    raw = message.get("data")
    if not raw:
        logger.warning("Received stream message with no 'data' field")
        return None
    try:
        data = json.loads(raw)
        return DisruptionSignal(**data)
    except Exception as exc:
        logger.error(f"Failed to parse stream message: {exc} — raw={raw[:200]}")
        return None


def consume_signals(
    handler: Callable[[DisruptionSignal], None],
    batch_size: int = _DEFAULT_BATCH,
    block_ms: int = _DEFAULT_BLOCK_MS,
) -> None:
    """
    Consume signals from the Redis stream in an infinite loop.

    For each message:
      1. Deserialise → DisruptionSignal
      2. Call handler(signal)
      3. XACK on success (keeps message pending on handler failure for retry)

    Stops cleanly on KeyboardInterrupt.

    Args:
        handler:    Callable that receives a DisruptionSignal and processes it.
        batch_size: Number of messages to read per XREADGROUP call.
        block_ms:   Milliseconds to block waiting for messages.
    """
    client = get_redis_client()
    ensure_stream_and_group(client)
    logger.info(f"Starting consumer loop on stream='{STREAM_KEY}' group='{CONSUMER_GROUP}'")

    try:
        while True:
            entries = client.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {STREAM_KEY: ">"},   # ">" means undelivered messages only
                count=batch_size,
                block=block_ms,
            )
            if not entries:
                continue  # timeout — loop and block again

            for stream_name, messages in entries:
                for entry_id, fields in messages:
                    signal = _parse_message(fields)
                    if signal is None:
                        # Unparseable message — ACK to remove from pending list
                        client.xack(STREAM_KEY, CONSUMER_GROUP, entry_id)
                        continue
                    try:
                        handler(signal)
                        # Only ACK after successful handler execution
                        client.xack(STREAM_KEY, CONSUMER_GROUP, entry_id)
                        logger.info(f"Processed signal {signal.signal_id} (entry {entry_id})")
                    except Exception as exc:
                        logger.error(
                            f"Handler failed for signal {signal.signal_id} "
                            f"(entry {entry_id}): {exc} — message stays pending for retry"
                        )
    except KeyboardInterrupt:
        logger.info("Consumer loop stopped (KeyboardInterrupt)")


def consume_once(
    handler: Callable[[DisruptionSignal], None],
    batch_size: int = 10,
) -> int:
    """
    Non-blocking single-pass consumer — reads one batch, processes, returns count.

    Used in tests and CLI tools. Does not block waiting for new messages.

    Args:
        handler:    Callable that receives a DisruptionSignal.
        batch_size: Maximum messages to read in this pass.

    Returns:
        Number of signals successfully processed.
    """
    client = get_redis_client()
    ensure_stream_and_group(client)

    entries = client.xreadgroup(
        CONSUMER_GROUP,
        CONSUMER_NAME,
        {STREAM_KEY: ">"},
        count=batch_size,
        block=0,   # non-blocking
    )
    if not entries:
        return 0

    processed = 0
    for stream_name, messages in entries:
        for entry_id, fields in messages:
            signal = _parse_message(fields)
            if signal is None:
                client.xack(STREAM_KEY, CONSUMER_GROUP, entry_id)
                continue
            try:
                handler(signal)
                client.xack(STREAM_KEY, CONSUMER_GROUP, entry_id)
                processed += 1
            except Exception as exc:
                logger.error(f"Handler failed for {signal.signal_id}: {exc}")

    return processed


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    def _print_signal(signal: DisruptionSignal) -> None:
        import json
        print(json.dumps(signal.model_dump(mode="json"), indent=2, default=str))

    print(f"Listening on stream '{STREAM_KEY}' — Ctrl+C to stop")
    consume_signals(_print_signal)
