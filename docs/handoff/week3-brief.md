# Week 3 Brief — SCDF Agent Development

**Written for:** Claude Code at the start of Week 3 session.

---

## What SCDF Is

SCDF (Supply Chain Disruption Forecaster) is a multi-agent AI system that:
1. Ingests real-time disruption signals (weather, port closures, tariffs, demand spikes, geopolitical events)
2. Runs probabilistic P10/P50/P90 scenario forecasting using Prophet and historical Qdrant data
3. Passes scenarios through an adversarial bull/bear debate crew (gpt-4o) for stress-testing
4. Outputs ranked response playbooks stored in Qdrant and S3

The system is built with CrewAI v1.14+ Flows + Crews architecture. All LLM calls route through Helicone proxy. All traces appear in Langfuse (self-hosted, Langfuse SDK v4.x).

---

## Current State of the Repo (End of Week 2)

### What exists and works:
```
src/config/settings.py            — pydantic-settings singleton, all env vars
src/config/helicone.py            — OpenAI client factory with Helicone proxy
src/config/llm_config.py          — get_primary_llm() / get_debate_llm() for CrewAI
src/memory/qdrant_client.py       — Qdrant client, setup_collections(), get_embedding()
src/signals/mock_generator.py     — DisruptionSignal model + 5 templates + stream_signals()
src/models/outputs.py             — 8 Pydantic output models (agent contracts)
src/models/__init__.py            — exports all 8 models
src/observability/langfuse_tracer.py — Langfuse 4.x tracing: trace_agent decorator,
                                       create_run_trace(), get_tracer()
src/observability/__init__.py     — exports tracer functions
src/agents/signal_ingester.py     — stub agent + traced run() → SignalAnalysis
src/agents/scenario_builder.py    — stub agent + traced run() → ScenarioSet
src/agents/impact_modeler.py      — stub agent + traced run() → ImpactAnalysis
src/agents/bull_analyst.py        — stub agent (gpt-4o) + traced run() → AnalystPosition
src/agents/bear_analyst.py        — stub agent (gpt-4o) + traced run() → AnalystPosition
src/agents/playbook_writer.py     — stub agent + traced run() → Playbook
src/agents/__init__.py            — exports all 6 agents + tasks + run() functions
src/flows/disruption_flow.py      — DisruptionFlow with FlowState, 8 steps,
                                    fast-path/full-debate router, parallel debate
src/flows/__init__.py             — exports DisruptionFlow, FlowState, run
scripts/run_crew.py               — Rich-formatted crew runner (--type --severity)
scripts/verify_langfuse.py        — Langfuse span verification script
scripts/test_connections.py       — 6-check health probe with Rich output
scripts/seed_qdrant.py            — seeds 60 disruptions + 60 responses, idempotent
tests/test_week1.py               — Week 1 test suite
tests/test_week2.py               — 27 tests: models, FlowState, routing, stubs, imports
docker-compose.yml                — Qdrant (port 6333) + Langfuse (port 3000) + Postgres
Makefile                          — all targets including week2
```

### Verified end-to-end:
- `make run-crew --type port --severity 8` → full 6-agent crew, Playbook JSON in ~1.5s
- `make run-crew --type weather --severity 2` → fast-path, 4 agents, Playbook JSON
- `pytest tests/test_week2.py` → 27 passed, 0 failed
- Fast-path route activates correctly when `severity < 4`
- Full-debate route activates correctly when `severity >= 4`
- All 6 agents trace to Langfuse via `@trace_agent` decorator

### Qdrant state:
- `disruptions` collection: 60 records seeded
- `responses` collection: 60 records seeded
- `playbooks` collection: empty (populated in Week 7)

---

## Week 3 Objectives

### Primary deliverable: Wire real data into Scenario Builder and Impact Modeler; add RAGAS evaluation

**1. Wire Prophet P10/P50/P90 into `scenario_builder.py`**

Replace the stub in `src/agents/scenario_builder.py::run()` with a real Prophet forecast:
- Use historical resolution_days from the 60 Qdrant `disruptions` records as time-series input
- Generate P10/P50/P90 confidence intervals via Prophet
- Convert interval outputs to `Scenario` Pydantic objects
- Keep the CrewAI Agent/Task definitions unchanged — only replace the stub data in `run()`

The signal's `disruption_type` and `region` should filter the Qdrant records used as training data.

**2. Wire real Qdrant semantic search into `impact_modeler.py`**

Replace the hardcoded precedents in `src/agents/impact_modeler.py::run()`:
- Call `get_embedding(signal.description)` → 1536-dim vector
- Call `get_qdrant_client().search(collection_name="disruptions", query_vector=embedding, limit=3)`
- Parse `ScoredPoint` results into `HistoricalPrecedent` objects
- Map `point.score` → `similarity_score`, `point.payload` → remaining fields
- Handle gracefully if Qdrant is unavailable (fall back to stub data with a warning)

**3. Add Redis Streams signal consumer**

Create `src/signals/redis_consumer.py` that:
- Consumes from Upstash Redis Streams using `XREAD` with consumer group
- Deserialises each message into a `DisruptionSignal`
- Calls `disruption_flow.run(signal)` for each consumed signal
- Commits the stream offset after successful processing

**4. Create `src/evaluation/ragas_scorer.py`**

Wire RAGAS to evaluate playbook quality on every crew run:
- Use `playbook.ragas_context` (the list of retrieved precedent texts) as the RAG context
- Use `playbook.actions[0].action` (top recommended action) as the answer
- Use the original signal description as the question
- Score on: answer relevancy, context recall, faithfulness
- Return a `RagasScore` Pydantic model with per-metric scores

**5. Create `scripts/evaluate_playbook.py`**

Script that:
- Runs the full crew on 5 different signal types
- Evaluates each resulting playbook with `ragas_scorer`
- Prints a per-signal RAGAS score table using Rich
- Fails (exit 1) if average answer relevancy < 0.5

**6. Add `tests/test_week3.py`**

Test coverage:
- `ScenarioSet.p10.probability == 0.10` with real Prophet output
- `ImpactAnalysis.precedents` has `len() == 3` with real Qdrant results
- `ImpactAnalysis.retrieval_quality > 0.0` (real similarity scores)
- `RagasScore` has all expected fields populated
- Fast path still works with real Impact Modeler

---

## Files Week 3 Will Create or Modify

### Modified files:
```
src/agents/scenario_builder.py    — replace stub with Prophet forecast call
src/agents/impact_modeler.py      — replace stub with real Qdrant retrieval
```

### New files:
```
src/signals/redis_consumer.py     — Upstash Redis Streams consumer
src/evaluation/__init__.py        — module init
src/evaluation/ragas_scorer.py    — RAGAS scoring on playbook outputs
scripts/evaluate_playbook.py      — RAGAS evaluation runner script
tests/test_week3.py               — Week 3 test suite
docs/week3-completion.md          — (create at week end)
docs/handoff/week4-brief.md       — (create at week end)
```

---

## Critical Constraints — Carry Forward Forever

1. **Tiered model strategy is non-negotiable.**
   - `get_primary_llm()` → gpt-4o-mini for all non-debate agents
   - `get_debate_llm()` → gpt-4o for bull/bear analysts ONLY
   - Never assign gpt-4o to workhorse agents

2. **Helicone proxy required on every LLM call.**
   - All `openai.OpenAI` clients must use `get_openai_client()` from `src/config/helicone.py`
   - All CrewAI `LLM` instances must use `get_primary_llm()` or `get_debate_llm()`
   - Never use `openai.OpenAI()` directly

3. **All LLM calls must appear in Langfuse.**
   - Use `@trace_agent(agent_name)` on every agent `run()` function
   - Call `lf.flush()` at the end of every Flow run (already in `persist_result`)
   - Langfuse SDK version is 4.x — API differs from 2.x significantly

4. **Qdrant interactions must be idempotent.**
   - Always use deterministic UUIDs (uuid5) for point IDs when upserting
   - Call `setup_collections()` at application startup

5. **Settings singleton is the single source of truth.**
   - Never hardcode model names, API keys, or collection names
   - Always use `get_settings()` from `src/config/settings.py`

6. **Stub run() functions must remain as fallbacks.**
   - When replacing a stub with a real implementation, keep the stub logic
     as a fallback path (e.g., on Qdrant connectivity failure)
   - The test suite must still pass without live Qdrant/LLM credentials

7. **Never break the `FlowState` contract.**
   - All fields in `FlowState` are optional (except `signal` which is set pre-kickoff)
   - The flow router reads `self.state.fast_path` — do not rename or remove it
   - `self.state.completed_at` must be set in both `write_playbook` and `fast_playbook`

---

## Key Files to Re-Read at Week 3 Start

Before writing any code, re-read:
- `src/agents/scenario_builder.py` — current stub, TODO WEEK 4 comment
- `src/agents/impact_modeler.py` — current stub, TODO WEEK 4 comment
- `src/memory/qdrant_client.py` — `get_qdrant_client()`, `get_embedding()`, collection schemas
- `src/flows/disruption_flow.py` — full flow structure to understand what week 3 changes affect
- `tests/test_week2.py` — all 27 tests must still pass after week 3 changes
- `requirements.txt` — check if `ragas`, `prophet`, `redis` are already listed before adding them
