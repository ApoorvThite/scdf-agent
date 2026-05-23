# SCDF — Supply Chain Disruption Forecaster

A production-grade multi-agent AI system that ingests real-time disruption signals, generates probabilistic P10/P50/P90 scenario forecasts, stress-tests them through an adversarial bull/bear debate crew, and outputs ranked response playbooks.

---

## Architecture Overview

| Tool | Role | Cost |
|---|---|---|
| CrewAI v1.12+ (Flows + Crews) | Multi-agent orchestration | Free OSS |
| OpenAI gpt-4o-mini | Workhorse agents (5 of 6) | ~$0.15/1M tokens |
| OpenAI gpt-4o | Debate agents (bull + bear) | ~$5/1M tokens |
| Helicone (hobby) | LLM gateway + cost tracking | Free ≤ 100k req/mo |
| Qdrant (Docker) | Vector DB — 3 collections | Free self-hosted |
| Langfuse (Docker) | LLM observability + tracing | Free self-hosted |
| Upstash Redis Streams | Signal bus | Free ≤ 10k cmd/day |
| AWS DynamoDB / S3 / SNS / Lambda | Persistence + alerts + scheduling | Always-free tier |
| Prophet | P10/P50/P90 time-series forecasting | Free OSS |
| React + Recharts + Vercel | Operations dashboard (Week 8) | Free hobby tier |

**Estimated monthly cost at 100 crew runs/day: $8–15** (dominated by gpt-4o debate agents).

See [docs/architecture.md](docs/architecture.md) for full technical details.

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/scdf-agent.git
cd scdf-agent

# 2. Install Python dependencies
make install

# 3. Configure environment
cp .env.example .env
# Edit .env with your OpenAI, Helicone, and Langfuse keys

# 4. Start Docker services (Qdrant + Langfuse)
make up
# Services take ~15 seconds to initialise

# 5. Verify all connections
make setup

# 6. Seed Qdrant with 60 historical disruption records
make seed

# 7. Run tests
make test

# OR: do everything in one command
make week1
```

**Service endpoints after `make up`:**
- Qdrant dashboard: http://localhost:6333/dashboard
- Langfuse dashboard: http://localhost:3000 (create account on first visit)

---

## Project Structure

```
scdf-agent/
├── .env.example             # All required environment variables
├── docker-compose.yml       # Qdrant + Langfuse + PostgreSQL
├── Makefile                 # install / up / down / setup / seed / test / week1
├── requirements.txt
├── docs/
│   ├── architecture.md      # Full system design, agent table, collection schemas
│   ├── week1-completion.md  # Week 1 deliverables + verification commands
│   └── handoff/
│       └── week2-brief.md   # Context brief for Week 2 session
├── src/
│   ├── config/
│   │   ├── settings.py      # pydantic-settings singleton
│   │   ├── helicone.py      # OpenAI client factory (Helicone proxy)
│   │   └── llm_config.py    # CrewAI LLM factory (tiered model strategy)
│   ├── agents/              # 6 CrewAI agents (built Week 2+)
│   ├── flows/               # CrewAI Flow DAG (built Week 2)
│   ├── tools/               # Custom CrewAI tools (built Week 3+)
│   ├── memory/
│   │   └── qdrant_client.py # Qdrant factory + collection setup + embedding
│   └── signals/
│       └── mock_generator.py# DisruptionSignal model + local stream simulator
├── scripts/
│   ├── test_connections.py  # 6-check health probe
│   └── seed_qdrant.py       # Seeds 60 disruptions + 60 responses
└── tests/
    └── test_week1.py        # pytest suite
```

---

## Week-by-Week Build Plan

| Week | Milestone |
|---|---|
| **1** ✅ | Scaffold, Qdrant + Langfuse, Helicone proxy, mock signals, 60 seed records |
| 2 | Stub CrewAI Flow + all 6 agents, Langfuse tracing per step, Qdrant retrieval stub |
| 3 | Signal Ingester live, Redis Streams consumer, DynamoDB persistence |
| 4 | Scenario Builder + Prophet P10/P50/P90 forecasting |
| 5 | Impact Modeler with full Qdrant RAG retrieval |
| 6 | Bull/Bear debate crew with structured argument schema |
| 7 | Playbook Writer + S3 + SNS alerts + AWS Lambda scheduling |
| 8 | React dashboard + Vercel deployment + end-to-end integration test |

---

## Running Tests

```bash
# All tests (skips Qdrant tests if not running)
make test

# Verbose with coverage
pytest tests/ -v

# Unit tests only (no Docker required)
pytest tests/ -v -m "not integration"
```

---

## Cost Breakdown

| Service | Free Tier | Estimated Usage | Cost |
|---|---|---|---|
| OpenAI gpt-4o-mini | Pay-per-use | ~5M tokens/mo | ~$0.75/mo |
| OpenAI gpt-4o (debate only) | Pay-per-use | ~500k tokens/mo | ~$7.50/mo |
| Helicone | 100k req/mo free | ~3k req/mo | $0 |
| Qdrant | Self-hosted | — | $0 |
| Langfuse | Self-hosted | — | $0 |
| Upstash Redis | 10k cmd/day free | ~500 cmd/day | $0 |
| AWS (DynamoDB + S3 + SNS + Lambda) | Always-free tiers | Well within limits | $0 |
| Vercel (dashboard) | Hobby tier | 1 project | $0 |
| **Total** | | | **~$8–15/mo** |

---

## Links

- [Architecture](docs/architecture.md)
- [Week 1 Completion](docs/week1-completion.md)
- [Week 2 Brief](docs/handoff/week2-brief.md)
