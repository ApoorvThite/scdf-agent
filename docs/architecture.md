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

| Week | Milestone |
|---|---|
| 1 | Project scaffold, Qdrant + Langfuse setup, Helicone proxy, mock signals, 60 seed records |
| 2 | Stub CrewAI Flow + all 6 stub agents, Langfuse trace per agent step, Qdrant retrieval wired |
| 3 | Signal Ingester agent fully functional, Redis Streams consumer, DynamoDB persistence |
| 4 | Scenario Builder + Prophet P10/P50/P90 forecasting integrated |
| 5 | Impact Modeler with full Qdrant RAG retrieval pipeline |
| 6 | Bull/Bear debate crew with structured argument schema + synthesis |
| 7 | Playbook Writer + S3 storage + SNS alerts + AWS Lambda scheduling |
| 8 | React dashboard (Recharts) + Vercel deployment + end-to-end integration test |

---

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
