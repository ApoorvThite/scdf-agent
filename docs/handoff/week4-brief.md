# Week 4 Brief — SCDF Agent Development

**Written for:** Claude Code at the start of Week 4 session.

---

## What SCDF Is

SCDF (Supply Chain Disruption Forecaster) is a multi-agent AI system that:
1. Ingests disruption signals (weather, port closures, tariffs, demand spikes, geopolitical events)
2. Runs probabilistic P10/P50/P90 scenario forecasting using Prophet and Qdrant-seeded historical data
3. Passes scenarios through an adversarial bull/bear debate crew (gpt-4o) for stress-testing
4. Outputs ranked response playbooks evaluated for quality via a manual RAGAS layer

All LLM calls route through Helicone proxy. All agent executions appear as named spans in Langfuse (SDK v4.x). All state lives in `FlowState` — agents are stateless functions.

---

## Current State of the Repo (End of Week 3)

### What works and is real (not stubbed):

```
src/forecasting/prophet_engine.py       — real Prophet P10/P50/P90 forecasting
src/agents/scenario_builder.py          — real implementation via ProphetEngine
src/memory/qdrant_retrieval.py          — real Qdrant 3-tier broadening search
src/agents/impact_modeler.py            — real Qdrant RAG retrieval with fallback
src/evaluation/ragas_scorer.py          — real manual RAGAS (faithfulness/relevance/precision)
src/flows/disruption_flow.py            — RAGAS wired into persist_result step
```

### Still stub (next to replace):

```
src/agents/signal_ingester.py           — stub: returns hardcoded SignalAnalysis
src/agents/playbook_writer.py           — stub: returns hardcoded Playbook
src/agents/bull_analyst.py              — stub: returns hardcoded AnalystPosition (position="bull")
src/agents/bear_analyst.py              — stub: returns hardcoded AnalystPosition (position="bear")
```

### Full file inventory:

```
src/config/settings.py                  — pydantic-settings singleton, all env vars
src/config/helicone.py                  — get_openai_client(agent_name) factory with Helicone
src/config/llm_config.py                — get_primary_llm() / get_debate_llm()
src/memory/qdrant_client.py             — get_qdrant_client(), setup_collections(), get_embedding()
src/memory/qdrant_retrieval.py          — retrieve_similar_disruptions(), format_precedents(), etc.
src/signals/mock_generator.py           — DisruptionSignal + 5 type templates + stream_signals()
src/models/outputs.py                   — 8 Pydantic output models — DO NOT MODIFY
src/models/__init__.py                  — exports all 8 models
src/observability/langfuse_tracer.py    — Langfuse 4.x: trace_agent, create_run_trace, get_tracer
src/observability/__init__.py           — exports tracer functions
src/forecasting/prophet_engine.py       — DisruptionForecastInput, generate_scenario_set()
src/agents/signal_ingester.py           — STUB → target for Week 4
src/agents/scenario_builder.py          — REAL (Prophet)
src/agents/impact_modeler.py            — REAL (Qdrant) with stub fallback
src/agents/bull_analyst.py              — STUB (gpt-4o)
src/agents/bear_analyst.py              — STUB (gpt-4o)
src/agents/playbook_writer.py           — STUB → target for Week 4
src/agents/__init__.py                  — exports all 6 agents + run() functions
src/flows/disruption_flow.py            — DisruptionFlow, FlowState, run()
src/evaluation/__init__.py              — empty module init
src/evaluation/ragas_scorer.py          — RAGASScore, evaluate_playbook()
scripts/run_crew.py                     — Rich crew runner with --type --severity CLI
scripts/verify_langfuse.py              — Langfuse span verification
scripts/evaluate_playbook.py            — RAGAS runner: 3 signal types, Rich table, JSON output
scripts/seed_qdrant.py                  — seeds 60 disruptions + 60 responses, idempotent
scripts/test_connections.py             — 6-check health probe
tests/test_week1.py                     — Week 1 test suite (15 tests)
tests/test_week2.py                     — Week 2 test suite (27 tests)
tests/test_week3.py                     — Week 3 test suite (21 unit + 1 integration class)
docker-compose.yml                      — Qdrant (6333) + Langfuse (3000) + Postgres
Makefile                                — all targets including week3
```

### Verified end-to-end (Week 3):

- `pytest tests/` → 63 passed, 0 failed (unit tests; integration tests require live Qdrant)
- Prophet engine: P10 lead_time > P90 lead_time ✓ (higher is worse, P10=worst case)
- Qdrant 3-tier broadening: returns precedents even on type+region miss ✓
- RAGAS evaluate_playbook: calls gpt-4o-mini 3× and produces RAGASScore ✓
- Flow persist_result: wires RAGAS, stores in FlowState.ragas_score ✓
- Fast path (severity < 4) still routes correctly and completes without debate ✓

---

## Week 4 Objectives

### Primary deliverable: Real LLM in signal_ingester + Redis Streams consumer + DynamoDB persistence

**1. Wire real gpt-4o-mini into `signal_ingester.py`**

Replace the stub `run()` with a real CrewAI Task execution that:
- Receives the `DisruptionSignal` as context
- Returns a valid `SignalAnalysis` Pydantic model (JSON-mode output)
- Sets `requires_full_crew = True` when `severity_score >= 4`
- Retains the stub as a `try/except` fallback

The existing CrewAI Agent definition and `@trace_agent("signal_ingester")` decorator must remain unchanged. Only the stub data in `run()` should be replaced with a real `.kickoff()` call.

**2. Wire real gpt-4o-mini into `playbook_writer.py`**

Replace the stub `run()` with a real CrewAI Task that:
- Receives scenario set + impact analysis + (optionally) bull/bear positions as context
- Returns a valid `Playbook` with 5 `PlaybookAction` items ranked by priority
- Populates `ragas_context` with a list of cited precedent descriptions (needed for RAGAS)
- Retains the stub as a `try/except` fallback

**3. Create `src/signals/redis_consumer.py`**

Upstash Redis Streams consumer that:
- Connects to `UPSTASH_REDIS_URL` (from settings)
- Reads from stream key `scdf:signals` using `XREAD` with consumer group `scdf-consumer-group`
- Deserialises each entry into a `DisruptionSignal`
- Calls `disruption_flow.run(signal)` for each message
- ACKs the message (`XACK`) after successful processing
- Handles connection failures gracefully (exponential backoff)

Required new env vars to add to `.env.example`:
```
UPSTASH_REDIS_URL=rediss://...
UPSTASH_REDIS_TOKEN=...
```

**4. Create `src/persistence/dynamo_store.py`**

DynamoDB persistence for completed flow runs:
- `upsert_disruption(signal, playbook) -> str`: writes to `scdf-disruptions` table, returns item key
- `upsert_playbook(playbook, ragas_score) -> str`: writes to `scdf-playbooks` table
- Uses `boto3` with `get_settings().aws_region` (default: `us-east-1`)
- Graceful noop if `AWS_ACCESS_KEY_ID` not configured (dev mode)

Wire `dynamo_store.upsert_disruption()` and `upsert_playbook()` into `persist_result` step in the flow (the TODO WEEK 7 comment is wrong — DynamoDB was always planned for Week 4 in the revised plan).

**5. Update `tests/test_week4.py`**

Test coverage:
- `signal_ingester.run()` calls LLM and returns `SignalAnalysis` with all required fields
- `signal_ingester.run()` falls back to stub on `openai.APIError`
- `playbook_writer.run()` returns `Playbook` with 5 actions
- `playbook_writer.run()` sets `ragas_context` with non-empty list
- `redis_consumer.consume_one()` deserialises a signal and calls `run_flow`
- `dynamo_store.upsert_disruption()` returns a key without error (mock boto3)

---

## Files Week 4 Will Create or Modify

### Modified files:
```
src/agents/signal_ingester.py           — replace stub with real LLM call
src/agents/playbook_writer.py           — replace stub with real LLM call
src/flows/disruption_flow.py            — wire DynamoDB in persist_result
.env.example                            — add UPSTASH_REDIS_URL, UPSTASH_REDIS_TOKEN
```

### New files:
```
src/signals/redis_consumer.py           — Upstash Redis Streams consumer
src/persistence/__init__.py             — module init
src/persistence/dynamo_store.py         — DynamoDB upsert functions
tests/test_week4.py                     — Week 4 test suite
docs/week4-completion.md               — (create at week end)
docs/handoff/week5-brief.md            — (create at week end)
```

---

## Critical Constraints — Carry Forward Forever

1. **Tiered model strategy is non-negotiable.**
   - `get_primary_llm()` → gpt-4o-mini for all non-debate agents (signal_ingester, scenario_builder, impact_modeler, playbook_writer)
   - `get_debate_llm()` → gpt-4o for bull/bear analysts ONLY
   - Never assign gpt-4o to workhorse agents

2. **Helicone proxy required on every LLM call.**
   - All `openai.OpenAI` clients must use `get_openai_client(agent_name=...)` from `src/config/helicone.py`
   - All CrewAI `LLM` instances must use `get_primary_llm()` or `get_debate_llm()`
   - Never use `openai.OpenAI()` directly

3. **All agent executions must appear in Langfuse.**
   - `@trace_agent(agent_name)` on every agent `run()` function — do not remove or skip
   - Langfuse SDK v4.x — uses `start_as_current_observation` (sync context manager), NOT `observe()`

4. **Do NOT modify `src/models/outputs.py`.**
   - All 8 Pydantic models are frozen. Agent output contracts must remain stable.

5. **Do NOT restructure `src/flows/disruption_flow.py`.**
   - Only `persist_result` additions are allowed (DynamoDB, SNS wiring)
   - `FlowState` can gain new fields but must not lose existing ones
   - Flow routing strings `"fast_path"` and `"full_debate"` are literals — don't change

6. **Stub run() functions must remain as fallbacks.**
   - When replacing a stub with a real LLM implementation, keep stub as `except` fallback
   - Unit tests must pass without live OpenAI/Qdrant/Redis credentials

7. **Settings singleton is the single source of truth.**
   - Never hardcode model names, API keys, collection names, or table names
   - Always use `get_settings()` from `src/config/settings.py`
   - Add new env vars to both `Settings` class and `.env.example`

8. **Qdrant interactions must be idempotent.**
   - Always use deterministic UUIDs (uuid5) for point IDs when upserting

---

## Key Files to Re-Read at Week 4 Start

Before writing any code, re-read:
- `src/agents/signal_ingester.py` — current stub structure and @trace_agent usage
- `src/agents/playbook_writer.py` — current stub; note `ragas_context` field in Playbook
- `src/models/outputs.py` — all 8 output models; especially `Playbook.ragas_context` and `PlaybookAction.cited_precedent_id`
- `src/flows/disruption_flow.py` — full FlowState + persist_result; understand where DynamoDB fits
- `src/config/settings.py` — existing env vars; understand how to add new ones
- `tests/test_week3.py` — all 21 unit tests must still pass after Week 4 changes
- `docs/architecture.md` — full tech stack and flow execution paths

---

## Environment Setup

```bash
# Start Docker services (Qdrant + Langfuse)
colima start --cpu 2 --memory 4    # if using Colima on Mac
make up                             # starts Qdrant + Langfuse

# Seed Qdrant
make seed

# Verify connections
make setup

# Run all tests (should be 63 passed)
make test

# Run a crew
make run-crew
make run-crew-port   # severity=8, triggers full debate path
```

Services:
- Qdrant dashboard: http://localhost:6333/dashboard
- Langfuse dashboard: http://localhost:3000
