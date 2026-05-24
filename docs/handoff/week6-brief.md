# Week 6 Brief — SCDF Agent Development

**Written for:** Claude Code at the start of Week 6 session.

---

## What SCDF Is

SCDF (Supply Chain Disruption Forecaster) is a multi-agent AI system that:
1. Ingests disruption signals from an Upstash Redis Streams bus
2. Runs probabilistic P10/P50/P90 scenario forecasting via Prophet
3. Passes scenarios through an adversarial bull/bear debate crew (gpt-4o)
4. Outputs ranked response playbooks, persisted to DynamoDB and scored by RAGAS

All LLM calls route through Helicone proxy. All agent executions appear as named spans in Langfuse (SDK v4.x). All state lives in `FlowState` — agents are stateless functions.

---

## Current State of the Repo (End of Week 5)

### What is REAL (all 6 agents are now live):

```
src/agents/signal_ingester.py           — REAL: gpt-4o-mini structured JSON output + fallback
src/agents/scenario_builder.py          — REAL: Prophet P10/P50/P90 forecasting
src/agents/impact_modeler.py            — REAL: Qdrant RAG retrieval (3-tier broadening)
src/agents/bull_analyst.py              — REAL: gpt-4o adversarial debate (optimistic)
src/agents/bear_analyst.py              — REAL: gpt-4o adversarial debate (pessimistic)
src/agents/playbook_writer.py           — REAL: gpt-4o-mini confidence-weighted synthesis
src/evaluation/ragas_scorer.py          — REAL: manual RAGAS (faithfulness/relevance/precision)
src/ingestion/redis_consumer.py         — REAL: Upstash Redis Streams consumer
src/persistence/dynamodb.py             — REAL: DynamoDB upsert + query (with GSIs)
src/notifications/sns_publisher.py      — REAL: SNS routing (dev-mode logging locally)
src/handlers/signal_handler.py          — REAL: Lambda handler + local_invoke()
src/flows/disruption_flow.py            — REAL: full flow with debate + persistence
src/prompts/__init__.py                 — load_prompt(name) helper
src/prompts/bull_analyst.txt            — bull analyst system prompt
src/prompts/bear_analyst.txt            — bear analyst system prompt
src/prompts/playbook_writer.txt         — playbook writer system prompt
src/prompts/prompt_validator.py         — DebateQualityReport + validate_debate_quality()
```

### Full file inventory:

```
src/config/settings.py                  — pydantic-settings, all env vars
src/config/helicone.py                  — get_openai_client(agent_name) factory
src/config/llm_config.py                — get_primary_llm() / get_debate_llm()
src/memory/qdrant_client.py             — get_qdrant_client(), setup_collections(), get_embedding()
src/memory/qdrant_retrieval.py          — retrieve_similar_disruptions(), format_precedents()
src/signals/mock_generator.py           — DisruptionSignal + 5 templates + stream_signals()
src/models/outputs.py                   — 8 Pydantic output models — DO NOT MODIFY
src/models/__init__.py                  — exports all 8 models
src/observability/langfuse_tracer.py    — Langfuse 4.x tracing: @trace_agent, create_run_trace, get_tracer
src/observability/__init__.py           — exports tracer functions
src/forecasting/prophet_engine.py       — DisruptionForecastInput, generate_scenario_set()
src/prompts/__init__.py                 — load_prompt(name) helper
src/prompts/bull_analyst.txt            — bull analyst system prompt
src/prompts/bear_analyst.txt            — bear analyst system prompt
src/prompts/playbook_writer.txt         — playbook writer system prompt
src/prompts/prompt_validator.py         — DebateQualityReport + validate_debate_quality(n_runs)
src/agents/signal_ingester.py           — REAL (Week 4)
src/agents/scenario_builder.py          — REAL (Week 3)
src/agents/impact_modeler.py            — REAL (Week 3)
src/agents/bull_analyst.py              — REAL (Week 5): gpt-4o + _bull_fallback()
src/agents/bear_analyst.py              — REAL (Week 5): gpt-4o + _bear_fallback()
src/agents/playbook_writer.py           — REAL (Week 5): gpt-4o-mini + _determine_dominant_scenario()
src/agents/__init__.py                  — exports all 6 agents + run() functions
src/flows/disruption_flow.py            — DisruptionFlow, FlowState, startup_check(), run()
src/evaluation/__init__.py              — module init
src/evaluation/ragas_scorer.py          — RAGASScore, evaluate_playbook()
src/ingestion/__init__.py               — exports publish_signal, consume_signals, consume_once
src/ingestion/redis_consumer.py         — Redis Streams consumer
src/persistence/__init__.py             — exports save_playbook_result, etc.
src/persistence/dynamodb.py             — DynamoDB persistence layer
src/notifications/__init__.py           — exports publish_playbook_alert
src/notifications/sns_publisher.py      — SNS alert publisher
src/handlers/__init__.py                — exports handler, local_invoke
src/handlers/signal_handler.py          — Lambda handler
scripts/run_crew.py                     — Rich crew runner (--type --severity)
scripts/run_full_crew.py                — 6-panel Rich crew runner (Week 5)
scripts/tune_prompts.py                 — Prompt tuning toolkit (--mode debate|playbook|validate)
scripts/verify_langfuse.py              — Langfuse span verification
scripts/evaluate_playbook.py            — RAGAS evaluation runner
scripts/publish_signal.py               — CLI to publish signals to Redis
scripts/run_pipeline.py                 — Full end-to-end pipeline demo
scripts/setup_aws.py                    — One-time AWS resource provisioning
scripts/seed_qdrant.py                  — 60-record Qdrant seeder
scripts/test_connections.py             — 6-check health probe
tests/test_week1.py                     — 15 tests
tests/test_week2.py                     — 27 tests
tests/test_week3.py                     — 21 unit tests
tests/test_week4.py                     — 24 unit tests
tests/test_week5.py                     — 25 unit tests + 1 integration test
docker-compose.yml                      — Qdrant (6333) + Langfuse (3000) + Postgres
Makefile                                — all targets including week5
```

### Verified end-to-end (Week 5):

- `pytest tests/ -k "not integration"` → 112 passed, 0 failed
- Bull analyst: gpt-4o returns structured JSON → AnalystPosition with position="bull" ✓
- Bear analyst: gpt-4o returns structured JSON → AnalystPosition with position="bear" ✓
- Playbook writer: gpt-4o-mini synthesises debate → Playbook with 5 actions ✓
- Position constraints enforced in Python (bull never P10, bear never P90) ✓
- `_determine_dominant_scenario()`: confidence gap formula correct for all 4 cases ✓
- `ragas_context` populated from precedent descriptions (not LLM-generated) ✓
- Fabricated `cited_precedent_id` values stripped before Playbook construction ✓
- `asyncio.gather(return_exceptions=True)` handles debate agent failures gracefully ✓
- `run_full_crew.py`: 6-panel Rich output renders correctly ✓

---

## Week 6 Objectives

### Primary deliverable: Observability, storage, and hardening

**1. S3 playbook artifact storage (`src/persistence/s3_store.py`)**

Store each completed Playbook as a JSON artifact in S3:
- `save_playbook_artifact(playbook: Playbook, run_id: str) -> str` — returns S3 URL
- Key pattern: `playbooks/{signal_id}/{run_id}.json`
- Always idempotent (put_object overwrites on retry)
- Returns empty string on failure — infra errors must not crash the flow
- Wire into `persist_result` in `disruption_flow.py`

**2. Prompt versioning**

Track which prompt version was used for each run:
- Add `prompt_version: str` field to `src/prompts/__init__.py` (git SHA hash of prompt files)
- Log `prompt_version` as a Langfuse span attribute on each debate agent call
- Include `prompt_version` in the DynamoDB item saved by `save_playbook_result`
- This enables A/B comparison of prompt iterations in Langfuse

**3. Debate quality CI gate (`tests/test_debate_quality.py`)**

Automated debate quality regression test:
- `test_debate_quality_passes_threshold` — runs `validate_debate_quality(n_runs=3)` and asserts `report.passed`
- Skip if `OPENAI_API_KEY` not set (integration test)
- Also validate that `avg_confidence_gap > 0.08` as a softer pre-warning threshold

**4. Streaming output from debate agents**

Replace blocking `client.chat.completions.create()` with streaming in both analyst agents:
- Use `client.chat.completions.create(stream=True)` with `for chunk in response`
- Collect chunks into a single string before JSON parsing
- Log streaming token count to Langfuse as a span attribute
- Streaming enables real-time Langfuse token tracking

**5. Real-time Langfuse prompt tracking**

Associate each LLM call with its prompt file version:
- `trace_agent` decorator should accept an optional `prompt_name` argument
- When `prompt_name` is provided, add it as a Langfuse span input attribute
- This allows filtering Langfuse traces by prompt version

**6. Monitoring dashboard script (`scripts/monitor.py`)**

Rich live-view of pipeline health:
- DynamoDB: last 10 playbooks (signal_id, risk_level, ragas score, timestamp)
- Langfuse: last 10 traces (run_id, agent spans, token counts)
- Redis: stream lag (how far behind the consumer group is)
- Auto-refreshes every 30 seconds with `rich.live.Live`

**7. Tests (`tests/test_week6.py`)**

- `test_s3_save_playbook_artifact_returns_url` — mock S3 PutObject, assert URL pattern
- `test_s3_save_returns_empty_string_on_error` — assert no exception raised
- `test_prompt_version_is_deterministic` — same prompt files → same version string
- `test_debate_quality_integration` — runs real debate, asserts `report.passed`

---

## Files Week 6 Will Create or Modify

### New files:
```
src/persistence/s3_store.py             — S3 playbook artifact storage
tests/test_week6.py                     — Week 6 test suite
tests/test_debate_quality.py            — Debate quality CI gate
scripts/monitor.py                      — Rich live monitoring dashboard
docs/week6-completion.md               — (create at week end)
docs/handoff/week7-brief.md            — (create at week end)
```

### Modified files:
```
src/prompts/__init__.py                 — add prompt_version (git SHA)
src/observability/langfuse_tracer.py   — add prompt_name attribute to trace_agent
src/flows/disruption_flow.py            — wire s3_store into persist_result
src/agents/bull_analyst.py              — streaming LLM call
src/agents/bear_analyst.py              — streaming LLM call
Makefile                                — week6, monitor targets
```

---

## Critical Constraints — Carry Forward Forever

1. **Tiered model strategy is non-negotiable.**
   - `get_primary_llm()` → gpt-4o-mini for all non-debate agents
   - `get_debate_llm()` → gpt-4o for bull/bear analysts ONLY
   - Week 6 must not add any new gpt-4o calls outside debate agents

2. **Helicone proxy required on every LLM call.**
   - All OpenAI clients from `get_openai_client(agent_name=...)`

3. **All agent executions must appear in Langfuse.**
   - `@trace_agent(agent_name)` on every agent `run()` function

4. **Do NOT modify `src/models/outputs.py`.**

5. **Do NOT restructure `src/flows/disruption_flow.py`.**
   - Only adding S3 save to `persist_result` is allowed

6. **Stub fallbacks must remain for all 3 debate agents.**
   - Week 6 LLM changes (streaming) must not break the fallback path

7. **Settings singleton is the single source of truth.**

8. **Qdrant interactions must be idempotent.**

9. **Position constraints enforced in Python, not solely in prompts.**
   - Bull never recommends P10 (demote to P50)
   - Bear never recommends P90 (demote to P50)

---

## Key Files to Re-Read at Week 6 Start

Before writing any code, re-read:
- `src/agents/bull_analyst.py` — streaming migration target
- `src/agents/bear_analyst.py` — streaming migration target
- `src/flows/disruption_flow.py` — persist_result (add S3 step)
- `src/prompts/__init__.py` — add prompt_version
- `src/observability/langfuse_tracer.py` — trace_agent decorator signature
- `tests/test_week5.py` — 25 tests that must still pass
- `docs/architecture.md` — tiered model strategy and flow paths

---

## Environment Setup

```bash
colima start --cpu 2 --memory 4    # Mac only, if using Colima
make up                             # Qdrant + Langfuse
make seed                           # Seed Qdrant
make test                           # Should show 112 passed, 0 failed
make run-full-crew-port             # Full 6-agent pipeline demo
```

Services:
- Qdrant: http://localhost:6333/dashboard
- Langfuse: http://localhost:3000
