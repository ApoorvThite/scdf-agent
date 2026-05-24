# Week 5 Completion Checklist

## Tasks Completed

- [x] **Task 1** — `src/prompts/` directory with `__init__.py` (`load_prompt(name)` helper), `bull_analyst.txt` (optimistic mandate, P90/P50 only, JSON schema), `bear_analyst.txt` (pessimistic mandate, P10/P50 only, JSON schema), `playbook_writer.txt` (synthesis mandate with confidence formula and 5-action rules)
- [x] **Task 2** — `src/agents/bull_analyst.py` (real gpt-4o): `run_bull_analysis_task(signal, scenario_set, impact_analysis)` via Helicone; forces `position="bull"` and demotes any P10 recommendation to P50; `_bull_fallback()` stub retained
- [x] **Task 3** — `src/agents/bear_analyst.py` (real gpt-4o): `run_bear_analysis_task(signal, scenario_set, impact_analysis)` via Helicone; forces `position="bear"` and demotes any P90 recommendation to P50; `_bear_fallback()` stub retained
- [x] **Task 4** — `src/agents/playbook_writer.py` (real gpt-4o-mini): `write_playbook_task(signal, scenario_set, impact_analysis, bull_position, bear_position)` via Helicone; `_determine_dominant_scenario()` pre-computes scenario using confidence gap formula; `ragas_context` populated from precedent descriptions; fabricated `cited_precedent_id` values are stripped; pads to exactly 5 actions
- [x] **Task 5** — `src/flows/disruption_flow.py` updated: `run_debate` passes full context (`scenario_set`, `impact_analysis`) to both analysts; `return_exceptions=True` in `asyncio.gather`; `_bull_fallback`/`_bear_fallback` imported for exception handling; `write_playbook` and `fast_playbook` pass full context to playbook writer
- [x] **Task 6** — `src/prompts/prompt_validator.py`: `DebateQualityReport` Pydantic model; `validate_debate_quality(n_runs)` runs N full debate iterations and computes avg confidence gap + scenario agreement rate; `run_validation_report()` renders Rich-formatted output; passes when gap > 0.10 AND agreement rate < 40%
- [x] **Task 7** — `scripts/run_full_crew.py`: 6-panel Rich output (Signal → Scenarios → Precedents → Debate → Playbook → RAGAS); bull and bear rendered side-by-side in debate panel; parallel thread execution for debate step; `--type` and `--severity` CLI args
- [x] **Task 8** — `scripts/tune_prompts.py`: `--mode debate|playbook|validate`; debate mode shows per-run confidence gaps and agreement; playbook mode shows action quality metrics; validate mode calls `run_validation_report()`
- [x] **Task 9** — `Makefile`: `run-full-crew`, `run-full-crew-port`, `tune-debate`, `validate-debate`, `validate-prompts`, `week5` targets added
- [x] **Task 10** — `tests/test_week5.py`: 25 unit tests + 1 integration test covering prompt library, bull/bear LLM call + fallback, position constraints (bull never P10, bear never P90), debate disagreement, playbook 5-action requirement, ragas_context from precedents, precedent ID validation, dominant scenario formula (4 cases), DebateQualityReport structure
- [x] **Task 11** — Documentation: this file, `docs/handoff/week6-brief.md`
- [x] **Task 12** — GitHub commit and push

---

## Test Results

```
112 passed, 4 deselected (integration), 0 failed
```

All week 1, 2, 3, 4, and 5 unit tests pass without live services.

---

## How to Verify

```bash
# Full week 5 pipeline (requires Docker services up + env vars)
make week5

# Individual steps
make run-full-crew           # Full 6-agent crew with Rich 6-panel output
make run-full-crew-port      # Port/severity-8 (forces full debate path)
make validate-prompts        # Debate quality validation (3 runs)
make validate-debate         # Debate quality validation (5 runs)
make tune-debate             # Per-run confidence gap table

pytest tests/test_week5.py -v -k "not integration"   # 25 tests, 0 failures
pytest tests/ -v -k "not integration"                 # 112 tests, 0 failures
```

---

## Architecture Changes (Week 5)

### Prompt library (`src/prompts/`)

Three system prompt files are loaded at call time via `load_prompt(name)`. Prompts are never hardcoded inside Python files. Loading at call time (not module import time) means tests don't touch the filesystem during module loading.

### Adversarial debate constraints

Each analyst's `run()` function enforces position constraints **in Python after parsing the LLM response** — it never relies solely on the prompt:

| Agent | Forbidden recommendation | Override action |
|-------|--------------------------|-----------------|
| Bull  | P10 (worst case)         | Demote to P50   |
| Bear  | P90 (best case)          | Demote to P50   |

This ensures genuine disagreement is structurally enforced, not just prompted.

### Dominant scenario formula

Pre-computed in `_determine_dominant_scenario()` before the LLM call — the result is included in the playbook writer's user prompt so the model knows which label to use:

```
bear.confidence > bull.confidence + 0.15  → P10 label
bull.confidence > bear.confidence + 0.15  → P90 label
otherwise                                  → P50 label
```

### Debate quality validation

`src/prompts/prompt_validator.py` provides `validate_debate_quality(n_runs=5)` which:
- Runs N full debate iterations on a port/severity-8 signal
- Computes avg confidence gap and scenario agreement rate
- Returns `passed=True` when gap > 0.10 AND agreement_rate < 40%

---

## Decision Log

### Why Python-enforced position constraints instead of prompt-only

LLMs occasionally "break role" under adversarial pressure or unusual inputs. Relying solely on the prompt instruction ("never recommend P10") is insufficient — the constraint must be enforced in the response parser. The Python-side enforcement is invisible to the model but always fires.

### Why `return_exceptions=True` in `asyncio.gather`

Without `return_exceptions=True`, if either analyst raises, the exception propagates and kills the flow step. With it, exceptions are returned as values, and the flow handles them individually using the fallback function. This preserves the parallel execution while ensuring resilience.

### Why `ragas_context` is populated from `impact_analysis.precedents`

The RAGAS evaluator (`evaluate_playbook`) needs ground-truth context to measure faithfulness. The historical precedent descriptions are the only verifiable facts in the pipeline. Populating `ragas_context` in Python (not delegating to the LLM) ensures this is deterministic and correct even when the LLM fails.

### Why fabricated `cited_precedent_id` values are stripped

The LLM occasionally generates plausible-looking UUIDs that don't match any real Qdrant record. Retaining these would cause RAGAS and audit tools to follow broken links. The post-processing step `if cited_id not in valid_ids: cited_id = None` removes any IDs not in the `impact_analysis.precedents` set.

---

## Known Gaps (Deferred to Week 6+)

| Gap | Deferred To | File |
|---|---|---|
| S3 playbook artifact storage | Week 6 | `src/persistence/s3_store.py` |
| Streaming output from debate agents | Week 6 | `src/agents/bull_analyst.py`, `bear_analyst.py` |
| Prompt versioning (track which prompt version was used per run) | Week 6 | `src/prompts/` |
| Debate quality regression gate in CI | Week 6 | `tests/test_debate_quality.py` |
| Real-time Langfuse prompt tracking | Week 6 | `src/observability/` |
