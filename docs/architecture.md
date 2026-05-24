# SCDF Architecture — Supply Chain Disruption Forecaster

## Project Description

SCDF is a production-grade multi-agent AI system that continuously monitors global supply chain disruption signals (weather events, port closures, tariff changes, demand spikes, and geopolitical incidents), generates probabilistic P10/P50/P90 scenario forecasts using a structured CrewAI Flow, passes scenarios through an adversarial bull/bear debate crew for stress-testing, and outputs ranked response playbooks stored in Qdrant for retrieval-augmented decision support.

---

## Tech Stack

| Tool | Role | Cost | Why Chosen |
|---|---|---|---|
| CrewAI v1.12+ (Flows + Crews) | Multi-agent orchestration | Free OSS | Native Flow DAG + Crew composition; best-in-class role/task abstractions |
| OpenAI gpt-4o-mini | Primary workhorse LLM (5 of 6 agents) | ~$0.15/1M tokens | 20× cheaper than gpt-4o; sufficient for structured JSON extraction |
| OpenAI gpt-4o | Debate LLM (bull + bear agents only) | ~$5/1M tokens | Adversarial reasoning quality noticeably better; used sparingly |
| Helicone (hobby, free) | LLM gateway proxy | Free ≤ 100k req/mo | Per-agent cost tracking, request logging, rate limit management |
| Qdrant (self-hosted Docker) | Vector database (3 collections) | Free self-hosted | Best OSS vector DB; fast cosine search; rich payload filtering |
| Langfuse (self-hosted Docker) | LLM observability + tracing | Free self-hosted | Full trace/span visibility per agent step; better than LangSmith for privacy |
| Upstash Redis Streams | Signal bus (Kinesis substitute) | Free ≤ 10k cmd/day | Serverless Redis Streams; no infrastructure to manage |
| AWS DynamoDB | Disruption event store | Always-free ≤ 25GB | Pay-per-request; zero cost at dev scale |
| AWS S3 | Playbook artifact storage | Always-free ≤ 5GB | Durable JSON/PDF playbook storage |
| AWS SNS | Alert notifications | Always-free ≤ 1M pub/mo | Push critical alerts to Slack/email webhooks |
| AWS Lambda + EventBridge | Scheduled trigger + compute | Always-free ≤ 1M req/mo | Serverless signal ingestion cron |
| Prophet (Meta) | Time-series forecasting | Free OSS | P10/P50/P90 intervals natively; interpretable seasonality |
| React + Recharts + Vercel | Operations dashboard | Free (Vercel hobby) | Week 8 delivery; zero-config deployment |

---

## CrewAI Agents

| Agent | Model | Role |
|---|---|---|
| Signal Ingester | gpt-4o-mini | Classifies raw signals, extracts structured metadata, deduplicates |
| Scenario Builder | gpt-4o-mini | Constructs P10/P50/P90 scenario narratives from signal + historical data |
| Impact Modeler | gpt-4o-mini | Retrieves similar past disruptions from Qdrant, estimates financial/time impact |
| Bull Analyst | **gpt-4o** | Argues the optimistic recovery scenario; challenges bear assumptions |
| Bear Analyst | **gpt-4o** | Argues the pessimistic scenario; identifies tail risks and failure modes |
| Playbook Writer | gpt-4o-mini | Synthesises debate output into ranked, actionable response playbook |

---

## Qdrant Collections (3 Namespaces)

### `disruptions` (1536-dim, cosine)
```
disruption_id:   str   — UUID primary key
disruption_type: str   — weather | port | tariff | demand | geopolitical
region:          str   — Asia-Pacific | Europe | North America | Middle East | Latin America | Africa
severity:        int   — 1 (minor) to 10 (catastrophic)
year:            int   — calendar year of event
resolution_days: int   — days until supply chain normalised
resolved:        bool  — whether the disruption was fully resolved
```

### `responses` (1536-dim, cosine)
```
response_id:     str   — UUID
disruption_id:   str   — FK → disruptions.disruption_id
actions_taken:   str   — free-text description of response actions
outcome:         str   — successful | partial | failed
resolution_days: int   — actual days to resolution
cost_usd_k:      float — estimated cost in thousands USD
```

### `playbooks` (1536-dim, cosine)
```
playbook_id:     str   — UUID
disruption_type: str   — same enum as disruptions
region:          str   — same enum as disruptions
severity_band:   str   — low (1-3) | medium (4-6) | high (7-10)
steps:           str   — JSON-encoded ordered list of action steps
p10_days:        int   — optimistic resolution days
p50_days:        int   — expected resolution days
p90_days:        int   — pessimistic resolution days
```

---

## Tiered Model Cost Strategy

All LLM calls are routed through Helicone for per-agent cost attribution.

- **PRIMARY tier** (gpt-4o-mini): signal ingestion, scenario building, impact modeling, playbook formatting. These tasks require structured JSON output and retrieval-augmented generation — gpt-4o-mini handles them reliably at 20× lower cost.
- **DEBATE tier** (gpt-4o): bull analyst + bear analyst only. The adversarial debate format requires nuanced multi-step reasoning, counter-argument construction, and edge-case identification. Quality delta vs. mini is significant enough to justify ~$0.50–1.00 per full crew run.

Estimated monthly cost at 100 crew runs/day: **$8–15 total** (dominated by debate agents).

---

## 8-Phase Build Plan

| Week | Milestone | Status |
|---|---|---|
| 1 | Project scaffold, Qdrant + Langfuse setup, Helicone proxy, mock signals, 60 seed records | ✅ Complete |
| 2 | Stub CrewAI Flow + all 6 stub agents, Langfuse trace per agent step, fast-path/full-debate routing | ✅ Complete |
| 3 | Prophet P10/P50/P90 forecasting (scenario_builder), Qdrant RAG retrieval (impact_modeler), RAGAS evaluation layer | ✅ Complete |
| 4 | Signal Ingester real LLM, Redis Streams consumer, DynamoDB persistence layer | ⬜ Upcoming |
| 5 | Bull/Bear debate crew with structured argument schema + synthesis | ⬜ Upcoming |
| 6 | Playbook Writer real LLM + S3 artifact storage | ⬜ Upcoming |
| 7 | SNS alerts + AWS Lambda scheduling + end-to-end integration test | ⬜ Upcoming |
| 8 | React dashboard (Recharts) + Vercel deployment | ⬜ Upcoming |

---

---

## Forecasting Layer (Week 3)

`src/forecasting/prophet_engine.py` replaces the stub scenario builder with real probabilistic forecasting.

### Synthetic Series Approach

Because we don't have live sensor feeds, the engine generates 365 days of synthetic daily KPI data by:

1. Starting from regional baseline values (e.g. AP baseline lead_time = 21 days)
2. Applying a disruption-type-specific perturbation pattern (step change + decay curve)
3. Scaling by `_severity_multiplier(severity)` → 1.0× at severity 1, 3.0× at severity 10
4. Adding Gaussian noise for realistic variation

Prophet then fits this series and returns `yhat_lower` (P10 bound) and `yhat_upper` (P90 bound) over a 30-day forecast horizon.

### P10/P50/P90 Derivation

**Lead time** (higher = worse):
- P10 (worst case): uses `yhat_upper.max()` → longest predicted lead time
- P50 (expected): uses `yhat.mean()` → central forecast
- P90 (best case): uses `yhat_lower.min()` → fastest predicted resolution

**Inventory level / service level** (lower = worse):
- P10 (worst case): uses `yhat_lower.min()` → deepest predicted drop
- P50 (expected): uses `yhat.mean()` → central forecast
- P90 (best case): uses `yhat_upper.max()` → best predicted outcome

Resolution window (P10/P50/P90 days) is derived from severity band (≤3 → 14/7/3, ≤6 → 35/14/7, ≤8 → 56/21/10, 10 → 90/35/14).

If Prophet fitting fails (e.g. timezone-aware timestamps from pandas), the engine falls back to linear interpolation from the same perturbation deltas.

---

## RAG Retrieval Strategy (Week 3)

`src/memory/qdrant_retrieval.py` implements a three-tier broadening search strategy:

1. **Attempt 1** — type-exact + region-exact + resolved=True filter
2. **Attempt 2** (< 2 results) — type-exact + resolved=True only (any region)
3. **Attempt 3** (still empty) — unfiltered vector search (any type/region)

Embeddings use `text-embedding-ada-002` via the Helicone proxy. The query string is constructed from disruption_type, region, severity_score, and affected_kpis to maximise semantic recall.

`retrieve_response_records()` fetches response records via Qdrant `scroll` with a `disruption_id` FK filter. `format_precedents()` zips disruption records with their corresponding response records and converts to `HistoricalPrecedent` Pydantic models.

If embedding or Qdrant connection fails, `retrieve_similar_disruptions()` returns an empty list (graceful degradation). `impact_modeler.run()` then falls back to three hardcoded stub precedents (similarity_score=0.0) so the flow always completes.

---

## RAGAS Evaluation Layer (Week 3)

`src/evaluation/ragas_scorer.py` implements three RAG quality metrics using gpt-4o-mini as judge — without the heavy `ragas` pip dependency.

| Metric | What it measures | Weight |
|---|---|---|
| Faithfulness | Are playbook actions grounded in the retrieved precedents? | 40% |
| Answer Relevance | Does the playbook address the signal's disruption type and region? | 30% |
| Context Precision | Are the retrieved precedents relevant to the query? | 30% |

**Threshold**: `overall >= 0.65` → `passed = True`

**Formula**: `overall = 0.4 × faithfulness + 0.3 × answer_relevance + 0.3 × context_precision`

Each metric calls `_call_llm()` which sends a zero-shot JSON prompt to gpt-4o-mini and parses `{"score": float, "reasoning": str}`. Scores default to 0.5 on parse failure so evaluation never blocks the flow.

The flow's `persist_result` step calls `evaluate_playbook()` inside a `try/except` so RAGAS failure never stops a flow run. Results are logged to Langfuse via `score_current_trace`.

The standalone `scripts/evaluate_playbook.py` runner mocks Langfuse and tests 3 signal types (port/8, weather/6, tariff/5), saving JSON results to `data/eval_results/`.

---

## Agent Output Contracts

Every agent returns a Pydantic model from `src/models/outputs.py`. No agent returns a plain string.

| Agent | Output Model | Key Fields |
|---|---|---|
| Signal Ingester | `SignalAnalysis` | `severity_score`, `severity_label`, `requires_full_crew`, `affected_kpis` |
| Scenario Builder | `ScenarioSet` | `p10`, `p50`, `p90` (each a `Scenario`), `forecast_confidence` |
| Impact Modeler | `ImpactAnalysis` | `precedents` (list of `HistoricalPrecedent`), `kpi_impacts`, `retrieval_quality` |
| Bull Analyst | `AnalystPosition` | `position="bull"`, `thesis`, `key_evidence`, `recommended_scenario` |
| Bear Analyst | `AnalystPosition` | `position="bear"`, `thesis`, `key_evidence`, `dissenting_risk` |
| Playbook Writer | `Playbook` | `actions` (list of `PlaybookAction`), `dominant_scenario`, `ragas_context` |

`PlaybookAction` fields: `priority`, `action`, `rationale`, `timeframe`, `cited_precedent_id`.

All models live in `src/models/outputs.py`. The `__init__.py` re-exports all of them.

---

## Flow Execution Paths

The `DisruptionFlow` (in `src/flows/disruption_flow.py`) uses a `@router` to branch on severity:

```
ingest_signal → build_scenarios → model_impact
                                       │
                          ┌────────────┴────────────┐
                     severity < 4              severity ≥ 4
                     (fast_path)               (full_debate)
                          │                        │
                    fast_playbook          run_debate (bull ∥ bear)
                          │                        │
                          └──────────┬─────────────┘
                                persist_result
                                (→ Playbook)
```

**Fast path** (severity < 4): skips the gpt-4o debate crew entirely.
Runs 4 agents: signal ingester → scenario builder → impact modeler → playbook writer.

**Full debate** (severity ≥ 4): runs all 6 agents.
Bull and bear analysts run **in parallel** via `asyncio.gather` + `asyncio.to_thread`.

The `@router` returns the string `"fast_path"` or `"full_debate"`. Downstream `@listen` methods
use these strings as triggers. The final `persist_result` step listens to both terminal branches
using stacked `@listen` decorators.

---

## Langfuse Trace Structure

Every crew run produces one top-level Langfuse trace with 4–6 child agent spans:

```
Trace: crew-run-{signal_id}   ← created by create_run_trace(signal_id)
  ├── Span: signal_ingester    ← @trace_agent("signal_ingester")
  ├── Span: scenario_builder   ← @trace_agent("scenario_builder")
  ├── Span: impact_modeler     ← @trace_agent("impact_modeler")
  ├── Span: bull_analyst       ← only on full-debate path
  ├── Span: bear_analyst       ← only on full-debate path
  └── Span: playbook_writer    ← @trace_agent("playbook_writer")
```

Trace context is propagated via a `ContextVar` (`_trace_context` in `src/observability/langfuse_tracer.py`).
`create_run_trace(signal_id)` sets the context at the start of `ingest_signal`.
Each `@trace_agent` decorated function reads the context and creates a child span automatically.

---

## How to Run Locally

```bash
# 1. Clone and install
git clone https://github.com/YOUR_USERNAME/scdf-agent.git
cd scdf-agent
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your real API keys

# 3. Start Docker services (Qdrant + Langfuse)
make up
# Wait ~15 seconds for services to initialise

# 4. Verify all connections
make setup

# 5. Seed Qdrant with historical data
make seed

# 6. Run tests
make test

# 7. Print a sample disruption signal
make signal

# OR run everything in sequence
make week1
```

Services will be available at:
- Qdrant dashboard: http://localhost:6333/dashboard
- Langfuse dashboard: http://localhost:3000
