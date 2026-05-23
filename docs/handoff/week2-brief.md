# Week 2 Brief — SCDF Agent Development

**Written for:** Claude Code at the start of Week 2 session.

---

## What SCDF Is

SCDF (Supply Chain Disruption Forecaster) is a multi-agent AI system that:
1. Ingests real-time disruption signals (weather, port closures, tariffs, demand spikes, geopolitical events)
2. Runs probabilistic P10/P50/P90 scenario forecasting using Prophet and historical Qdrant data
3. Passes scenarios through an adversarial bull/bear debate crew (gpt-4o) for stress-testing
4. Outputs ranked response playbooks stored in Qdrant and S3

The system is built with CrewAI v1.12+ Flows + Crews architecture. All LLM calls route through Helicone proxy. All traces appear in Langfuse (self-hosted).

---

## Current State of the Repo (End of Week 1)

### What exists and works:
```
src/config/settings.py       — pydantic-settings singleton, all env vars
src/config/helicone.py       — OpenAI client factory with Helicone proxy + per-agent headers
src/config/llm_config.py     — get_primary_llm() / get_debate_llm() for CrewAI
src/memory/qdrant_client.py  — Qdrant client, setup_collections(), get_embedding()
src/signals/mock_generator.py— DisruptionSignal model + 5 templates + stream_signals()
scripts/test_connections.py  — 6-check health probe with Rich output
scripts/seed_qdrant.py       — seeds 60 disruptions + 60 responses, idempotent
tests/test_week1.py          — pytest suite for all Week 1 modules
docker-compose.yml           — Qdrant (port 6333) + Langfuse (port 3000) + Postgres
Makefile                     — install / up / down / setup / seed / test / signal / week1
```

### Empty stubs awaiting Week 2:
```
src/agents/   — all 6 agents (.gitkeep only)
src/flows/    — main flow DAG (.gitkeep only)
src/tools/    — custom CrewAI tools (.gitkeep only)
```

### Qdrant state:
- `disruptions` collection: 60 records seeded
- `responses` collection: 60 records seeded
- `playbooks` collection: empty (populated in Week 7)

---

## Week 2 Objectives

### Primary deliverable: Stub CrewAI Flow + all 6 stub agents, with Langfuse tracing per step

**1. Create stub agents in `src/agents/`**

Create one file per agent. Each agent should be a valid CrewAI `Agent` with a meaningful `role`, `goal`, `backstory`, and a stub `task` that returns placeholder JSON. Agents to create:

| File | Agent name | LLM | Task description |
|---|---|---|---|
| `signal_ingester.py` | Signal Ingester | `get_primary_llm()` | Classify + structure a DisruptionSignal into standard schema |
| `scenario_builder.py` | Scenario Builder | `get_primary_llm()` | Build P10/P50/P90 scenario narratives from a signal |
| `impact_modeler.py` | Impact Modeler | `get_primary_llm()` | Retrieve similar disruptions from Qdrant, estimate impact |
| `bull_analyst.py` | Bull Analyst | `get_debate_llm()` | Argue optimistic recovery scenario |
| `bear_analyst.py` | Bear Analyst | `get_debate_llm()` | Argue pessimistic / tail-risk scenario |
| `playbook_writer.py` | Playbook Writer | `get_primary_llm()` | Synthesise debate into ranked response playbook |

**2. Create the main Flow in `src/flows/disruption_flow.py`**

Use CrewAI `Flow` with `@start`, `@listen`, `@router` decorators. The flow should have these stages:
1. `ingest_signal(signal: DisruptionSignal)` — calls Signal Ingester
2. `build_scenarios(ingested)` — calls Scenario Builder
3. `model_impact(scenarios)` — calls Impact Modeler with Qdrant retrieval
4. `run_debate(impact_report)` — spins up Bull + Bear crew in parallel
5. `write_playbook(debate_result)` — calls Playbook Writer, returns final playbook JSON

For Week 2, each stage can return stub/placeholder output. The Flow DAG must be wired correctly.

**3. Wire Langfuse `observe()` decorators**

Every agent task execution must produce a Langfuse trace span. Use `langfuse.observe()` or the `@observe` decorator. Each span should capture:
- `input`: the task input dict
- `output`: the task output dict
- `metadata`: `{"agent": agent_name, "model": model_name, "week": 2}`

**4. Wire Qdrant retrieval into Impact Modeler stub**

The Impact Modeler stub should call `get_qdrant_client().search()` against the `disruptions` collection using `get_embedding(signal.description)` as the query vector. Return top-5 similar historical disruptions as the retrieval context (even if the agent doesn't fully use them yet).

**5. Add `tests/test_week2.py`**

Cover: Flow instantiates without error, all 6 agents have required attributes, Impact Modeler stub returns retrieval results when Qdrant is live.

---

## Files Week 2 Will Create or Modify

### New files:
```
src/agents/signal_ingester.py
src/agents/scenario_builder.py
src/agents/impact_modeler.py
src/agents/bull_analyst.py
src/agents/bear_analyst.py
src/agents/playbook_writer.py
src/flows/disruption_flow.py
tests/test_week2.py
```

### Modified files:
```
src/agents/__init__.py      — export all 6 agents
src/flows/__init__.py       — export DisruptionFlow
docs/week2-completion.md    — (create at week end)
docs/handoff/week3-brief.md — (create at week end)
```

---

## Critical Constraints — Carry Forward Forever

1. **Tiered model strategy is non-negotiable.**
   - `get_primary_llm()` → gpt-4o-mini for all non-debate agents
   - `get_debate_llm()` → gpt-4o for bull/bear analysts ONLY
   - Never assign gpt-4o to workhorse agents. Monthly cost would jump 20×.

2. **Helicone proxy required on every LLM call.**
   - All `openai.OpenAI` clients must use `get_openai_client()` from `src/config/helicone.py`
   - All CrewAI `LLM` instances must use `get_primary_llm()` or `get_debate_llm()`
   - Never use `openai.OpenAI()` directly without the Helicone base_url + auth header
   - Every agent should set `Helicone-Property-Agent` to its snake_case role name

3. **All LLM calls must appear in Langfuse.**
   - Use `langfuse.observe()` around every agent task function
   - Flush Langfuse at the end of every Flow run: `lf.flush()`
   - Use `metadata={"agent": ..., "model": ..., "week": ...}` on every trace

4. **Qdrant interactions must be idempotent.**
   - Always use deterministic UUIDs (uuid5) for point IDs when upserting
   - Call `setup_collections()` at application startup

5. **Settings singleton is the single source of truth.**
   - Never hardcode model names, API keys, or collection names
   - Always use `get_settings()` from `src/config/settings.py`
