# Week 4 Completion Checklist

## Tasks Completed

- [x] **Task 1** — `src/agents/signal_ingester.py` (real LLM): replaced stub with gpt-4o-mini structured JSON output call via Helicone; `parse_signal_task` + `validate_signal_analysis` + `_rule_based_fallback`; all `TODO WEEK 4` comments removed
- [x] **Task 2** — `src/ingestion/redis_consumer.py` + `src/ingestion/__init__.py`: Upstash Redis Streams consumer with `ensure_stream_and_group`, `publish_signal`, `consume_signals` (infinite loop), `consume_once` (non-blocking); handles BUSYGROUP idempotently
- [x] **Task 3** — `scripts/publish_signal.py`: CLI for publishing mock signals to Redis stream; `--type`, `--severity`, `--region`, `--count` args; Rich table output with stream entry IDs
- [x] **Task 4** — `src/persistence/dynamodb.py` + `src/persistence/__init__.py`: full DynamoDB persistence; `ensure_table_exists` with 2 GSIs; `save_playbook_result(FlowState)` with float→Decimal conversion; `get_playbook_by_signal_id`; `list_recent_playbooks`
- [x] **Task 5** — `src/notifications/sns_publisher.py` + `src/notifications/__init__.py`: risk-based SNS routing; dev-mode logging (no real SNS needed locally); `publish_playbook_alert` never raises
- [x] **Task 6** — `src/flows/disruption_flow.py` (persist_result rewrite): real DynamoDB save + SNS publish + RAGAS eval in `persist_result`; `startup_check()` function runs `ensure_table_exists()` once per process; `logger` replaces print statements
- [x] **Task 7** — `src/handlers/signal_handler.py` + `src/handlers/__init__.py`: Lambda handler supports both EventBridge and direct invocation formats; `local_invoke(signal)` wrapper for local testing  
  _Note: module named `src/handlers/` not `src/lambda/` — `lambda` is a Python reserved keyword_
- [x] **Task 8** — `scripts/run_pipeline.py`: full end-to-end demo; publish→consume→Lambda→DynamoDB→SNS; Rich summary panel with signal details, top 3 actions, RAGAS scores, pipeline status
- [x] **Task 9** — `scripts/setup_aws.py`: provisions DynamoDB, S3, two SNS topics, EventBridge rule; idempotent; partial success acceptable; Rich checklist output
- [x] **Task 10** — `Makefile`: `publish-signal`, `publish-port`, `run-pipeline`, `run-pipeline-port`, `setup-aws`, `week4` targets added
- [x] **Task 11** — `tests/test_week4.py`: 24 unit tests covering signal_ingester LLM + fallback, severity labels, validate helper, DynamoDB float conversion + save/retrieve, SNS dev-mode + low-risk + error handling, Lambda 200/400/500 responses
- [x] **Task 12** — Documentation: this file, `docs/architecture.md` updated (agent status table, ingestion pipeline, persistence layer, notification routing sections), build plan marks week 4 complete, `docs/handoff/week5-brief.md`
- [x] **Task 13** — GitHub commit and push

---

## Test Results

```
87 passed, 3 deselected (integration), 0 failed
```

All week 1, 2, 3, and 4 unit tests pass without live services.

---

## How to Verify

```bash
# Full week 4 pipeline (requires Docker services up + env vars)
make week4

# Individual steps
make setup-aws             # Provision AWS resources (partial OK without real creds)
make run-pipeline          # Full signal→playbook→DynamoDB→SNS pipeline
make run-pipeline-port     # Port/severity 8 (full debate path)
make publish-signal        # Publish one signal to Redis
make publish-port          # Publish port/severity 8 to Redis

pytest tests/test_week4.py -v -k "not integration"   # 24 tests, 0 failures
```

---

## Sample DynamoDB Item Structure

After a successful `make run-pipeline`, the DynamoDB table contains items like:

```json
{
  "signal_id": "a4c7d8f2-...",
  "created_at": "2026-05-24T14:30:00.000Z",
  "run_id": "b1e2f3...",
  "completed_at": "2026-05-24T14:30:45.000Z",
  "fast_path": false,
  "region": "Asia-Pacific",
  "risk_level": "high",
  "disruption_type": "port",
  "signal": { "signal_id": "...", "description": "...", ... },
  "signal_analysis": { "severity_label": "high", "affected_kpis": [...], ... },
  "scenario_set": { "p10": {...}, "p50": {...}, "p90": {...}, ... },
  "impact_analysis": { "precedents": [...], "risk_level": "high", ... },
  "playbook": { "overall_risk": "high", "actions": [...], ... },
  "ragas_score": { "overall": 0.71, "passed": true, ... }
}
```

_Run `make run-pipeline` with valid AWS credentials and live services to populate real items._

---

## Decision Log

### Why dev-mode SNS logging instead of real SNS locally

Real SNS requires AWS credentials, an active topic ARN, and either a Lambda subscriber or a Slack/email webhook wired up. For local development, none of these are guaranteed. The `is_development` check in `publish_playbook_alert` means:
- Local runs always succeed (return True) without AWS credentials
- The alert message is logged at INFO level so it's still visible and testable
- Switching to production (`ENVIRONMENT=production` in `.env`) activates real SNS publish with zero code changes

### Why `src/handlers/` instead of `src/lambda/`

Python reserves `lambda` as a keyword for anonymous functions. `import src.lambda.signal_handler` is a `SyntaxError`. The module is named `src/handlers/` which is equally descriptive (it handles Lambda events) and valid Python.

### Why DynamoDB `PAY_PER_REQUEST` billing

On-demand billing means zero cost at dev scale (0–100 runs/day). Provisioned throughput requires capacity planning and wastes money during development. At production scale (>100K requests/day), switching to provisioned mode saves ~60% — that migration is straightforward and deferred to Week 7.

---

## Known Gaps (Deferred to Week 5+)

| Gap | Deferred To | File |
|---|---|---|
| Real LLM in bull_analyst | Week 5 | `src/agents/bull_analyst.py` |
| Real LLM in bear_analyst | Week 5 | `src/agents/bear_analyst.py` |
| Real LLM in playbook_writer | Week 5 | `src/agents/playbook_writer.py` |
| S3 playbook artifact storage | Week 6 | `src/persistence/s3_store.py` |
| Confidence calibration in playbook writer | Week 5 | `src/agents/playbook_writer.py` |
| True parallel debate execution validation | Week 5 | `src/flows/disruption_flow.py` |
