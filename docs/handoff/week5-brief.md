# Week 5 Brief — SCDF Agent Development

**Written for:** Claude Code at the start of Week 5 session.

---

## What SCDF Is

SCDF (Supply Chain Disruption Forecaster) is a multi-agent AI system that:
1. Ingests disruption signals from an Upstash Redis Streams bus
2. Runs probabilistic P10/P50/P90 scenario forecasting via Prophet
3. Passes scenarios through an adversarial bull/bear debate crew (gpt-4o)
4. Outputs ranked response playbooks, persisted to DynamoDB and scored by RAGAS

All LLM calls route through Helicone proxy. All agent executions appear as named spans in Langfuse (SDK v4.x). All state lives in `FlowState` — agents are stateless functions.

---

## Current State of the Repo (End of Week 4)

### What is REAL (not stubbed):

```
src/agents/signal_ingester.py           — REAL: gpt-4o-mini structured JSON output + fallback
src/agents/scenario_builder.py          — REAL: Prophet P10/P50/P90 forecasting
src/agents/impact_modeler.py            — REAL: Qdrant RAG retrieval (3-tier broadening)
src/evaluation/ragas_scorer.py          — REAL: manual RAGAS (faithfulness/relevance/precision)
src/ingestion/redis_consumer.py         — REAL: Upstash Redis Streams consumer
src/persistence/dynamodb.py             — REAL: DynamoDB upsert + query (with GSIs)
src/notifications/sns_publisher.py      — REAL: SNS routing (dev-mode logging locally)
src/handlers/signal_handler.py          — REAL: Lambda handler + local_invoke()
src/flows/disruption_flow.py            — REAL: persist_result wired with DynamoDB + SNS
```

### Still STUB (replacing this week):

```
src/agents/bull_analyst.py              — STUB: returns hardcoded AnalystPosition (position="bull")
src/agents/bear_analyst.py              — STUB: returns hardcoded AnalystPosition (position="bear")
src/agents/playbook_writer.py           — STUB: returns hardcoded Playbook
```

### Full file inventory:

```
src/config/settings.py                  — pydantic-settings, all env vars including new dynamodb_endpoint_url
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
src/agents/signal_ingester.py           — REAL (Week 4): LLM + fallback
src/agents/scenario_builder.py          — REAL (Week 3): Prophet
src/agents/impact_modeler.py            — REAL (Week 3): Qdrant RAG
src/agents/bull_analyst.py              — STUB (gpt-4o) → REPLACING WEEK 5
src/agents/bear_analyst.py              — STUB (gpt-4o) → REPLACING WEEK 5
src/agents/playbook_writer.py           — STUB → REPLACING WEEK 5
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
docker-compose.yml                      — Qdrant (6333) + Langfuse (3000) + Postgres
Makefile                                — all targets including week4
```

### Verified end-to-end (Week 4):

- `pytest tests/` → 87 passed, 0 failed (unit tests)
- Signal ingester: gpt-4o-mini returns structured JSON mapping to SignalAnalysis ✓
- Fallback: rule-based SignalAnalysis returned on any LLM failure ✓
- DynamoDB: `_floats_to_decimal` converts nested Pydantic model floats correctly ✓
- SNS: dev-mode returns True without calling boto3 ✓
- Lambda handler: returns 200 with playbook JSON, 400 on bad payload, 500 on flow error ✓

---

## Week 5 Objectives

### Primary deliverable: Replace the final 3 stubs with real gpt-4o and gpt-4o-mini LLM implementations

**1. Wire real gpt-4o into `bull_analyst.py`**

Replace the stub `run()` with a real CrewAI Task execution that:
- Receives the DisruptionSignal and the P50 scenario from FlowState as context
- Returns a valid `AnalystPosition` with `position="bull"`
- Argues the optimistic recovery case: why the situation will resolve faster/better than feared
- Cites `key_evidence` from the signal description and historical precedents
- Sets `recommended_scenario` to "P90 (best case)" or "P50 (base case)"
- Uses `get_debate_llm()` (gpt-4o) — the ONLY place gpt-4o is used in the pipeline
- Retains stub as `try/except` fallback

**2. Wire real gpt-4o into `bear_analyst.py`**

Mirror of bull_analyst but opposite position:
- Returns `AnalystPosition` with `position="bear"`
- Argues the pessimistic scenario: tail risks, failure modes, why P10 should be planned for
- Sets `recommended_scenario` to "P10 (worst case)" or "P50 (base case)"
- Uses `get_debate_llm()` (gpt-4o)
- Retains stub as `try/except` fallback

To achieve genuine disagreement between bull and bear:
- Bull system prompt: "You are an optimistic recovery specialist. Find reasons why this disruption will resolve faster than expected."
- Bear system prompt: "You are a risk analyst focused on tail risks. Find reasons why this disruption is worse than it appears."
- Both receive the same signal + P50 scenario as context

**3. Wire real gpt-4o-mini into `playbook_writer.py`**

Replace the stub `run()` with a real CrewAI Task that:
- Receives: signal + ScenarioSet + ImpactAnalysis + bull_position + bear_position from FlowState
- Returns a valid `Playbook` with 5 `PlaybookAction` items ranked by priority
- Populates `ragas_context` with the description strings from impact_analysis.precedents
- Sets `dominant_scenario` based on which analyst's position is more persuasive
- Sets `overall_risk` from impact_analysis.risk_level
- `cited_precedent_id` in each action should reference actual precedent record_ids where applicable
- Uses `get_primary_llm()` (gpt-4o-mini)
- Retains stub as `try/except` fallback

**4. Create `src/prompts/` directory**

Move all system prompts to separate `.txt` or `.md` files:
```
src/prompts/bull_analyst.txt         — bull analyst system prompt
src/prompts/bear_analyst.txt         — bear analyst system prompt
src/prompts/playbook_writer.txt      — playbook writer system prompt
src/prompts/__init__.py              — load_prompt(name: str) -> str helper
```

Keeping prompts in separate files:
- Makes them easy to iterate on without touching Python code
- Allows diff reviews of prompt changes separate from code changes
- Can be loaded at call time (not module load time) so tests don't hit the filesystem

**5. Update `src/flows/disruption_flow.py`**

The `run_debate` step currently calls `run_bull(self.state.signal)` and `run_bear(self.state.signal)`. Week 5 needs to also pass the ScenarioSet and ImpactAnalysis as context to the debate agents, since they need P50 scenario + precedents to form grounded arguments.

Update the call signatures:
```python
@listen(_FULL_DEBATE)
async def run_debate(self):
    bull_result, bear_result = await asyncio.gather(
        asyncio.to_thread(run_bull, self.state.signal, self.state.scenario_set, self.state.impact_analysis),
        asyncio.to_thread(run_bear, self.state.signal, self.state.scenario_set, self.state.impact_analysis),
    )
```

Update `run_playbook_writer` call similarly to pass full context:
```python
@listen(run_debate)
def write_playbook(self):
    self.state.playbook = run_playbook_writer(
        self.state.signal,
        self.state.scenario_set,
        self.state.impact_analysis,
        self.state.bull_position,
        self.state.bear_position,
    )
```

**6. Add `tests/test_week5.py`**

Test coverage:
- `bull_analyst.run()` returns AnalystPosition with position="bull"
- `bear_analyst.run()` returns AnalystPosition with position="bear"
- Bull and bear positions are genuinely different (different recommended_scenario)
- `playbook_writer.run()` returns Playbook with 5 actions
- `playbook_writer.run()` populates ragas_context from precedent descriptions
- `playbook_writer.run()` cites precedent record_ids in at least one action
- Full flow with real debate: FlowState has non-None bull_position and bear_position after kickoff

---

## Files Week 5 Will Create or Modify

### Modified files:
```
src/agents/bull_analyst.py              — replace stub with real gpt-4o call
src/agents/bear_analyst.py              — replace stub with real gpt-4o call
src/agents/playbook_writer.py           — replace stub with real gpt-4o-mini call
src/flows/disruption_flow.py            — update run_debate + write_playbook call signatures
```

### New files:
```
src/prompts/__init__.py                 — load_prompt() helper
src/prompts/bull_analyst.txt            — bull analyst system prompt
src/prompts/bear_analyst.txt            — bear analyst system prompt
src/prompts/playbook_writer.txt         — playbook writer system prompt
tests/test_week5.py                     — Week 5 test suite
docs/week5-completion.md               — (create at week end)
docs/handoff/week6-brief.md            — (create at week end)
```

---

## Critical Constraints — Carry Forward Forever

1. **Tiered model strategy is non-negotiable.**
   - `get_primary_llm()` → gpt-4o-mini for all non-debate agents
   - `get_debate_llm()` → gpt-4o for bull/bear analysts ONLY
   - Week 5 adds real gpt-4o calls — this is the ONLY place they should appear

2. **Helicone proxy required on every LLM call.**
   - All OpenAI clients from `get_openai_client(agent_name=...)` 
   - All CrewAI LLM instances from `get_primary_llm()` or `get_debate_llm()`

3. **All agent executions must appear in Langfuse.**
   - `@trace_agent(agent_name)` on every agent `run()` function

4. **Do NOT modify `src/models/outputs.py`.**

5. **Do NOT restructure `src/flows/disruption_flow.py`.**
   - Only updating `run_debate` and `write_playbook` call signatures is allowed
   - `FlowState` fields must not be removed

6. **Stub run() functions must remain as fallbacks.**
   - When real LLM implementation raises, stub data must be returned
   - Unit tests must pass without live OpenAI credentials

7. **Settings singleton is the single source of truth.**

8. **Qdrant interactions must be idempotent.**

---

## Key Files to Re-Read at Week 5 Start

Before writing any code, re-read:
- `src/agents/bull_analyst.py` — current stub structure, @trace_agent usage
- `src/agents/bear_analyst.py` — same
- `src/agents/playbook_writer.py` — current stub; `ragas_context` field; 4 current actions
- `src/models/outputs.py` — AnalystPosition, Playbook, PlaybookAction field contracts
- `src/flows/disruption_flow.py` — run_debate and write_playbook signatures
- `tests/test_week4.py` — 24 tests that must still pass
- `docs/architecture.md` — tiered model strategy and flow execution paths

---

## Environment Setup

```bash
colima start --cpu 2 --memory 4    # Mac only, if using Colima
make up                             # Qdrant + Langfuse
make seed                           # Seed Qdrant
make test                           # Should show 87 passed, 0 failed
make run-pipeline                   # Full pipeline demo
```

Services:
- Qdrant: http://localhost:6333/dashboard
- Langfuse: http://localhost:3000
