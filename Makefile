.PHONY: install up down setup seed test signal week1 run-crew run-crew-port verify-langfuse week2 forecast-test retrieval-test evaluate week3 publish-signal publish-port run-pipeline run-pipeline-port setup-aws week4 run-full-crew run-full-crew-port tune-debate validate-debate validate-prompts week5

install:
	pip install -r requirements.txt

up:
	docker-compose up -d

down:
	docker-compose down

setup:
	python scripts/test_connections.py

seed:
	python scripts/seed_qdrant.py

test:
	pytest tests/ -v

signal:
	python -m src.signals.mock_generator

week1: install up
	@echo "Waiting 15 seconds for services to start..."
	@sleep 15
	$(MAKE) setup
	$(MAKE) seed
	$(MAKE) test

run-crew:
	python -m scripts.run_crew

run-crew-port:
	python -m scripts.run_crew --type port --severity 8

verify-langfuse:
	python -m scripts.verify_langfuse

week2: up
	@echo "Waiting 15 seconds for services to start..."
	@sleep 15
	$(MAKE) run-crew
	$(MAKE) verify-langfuse
	$(MAKE) test

forecast-test:
	python -m src.forecasting.prophet_engine

retrieval-test:
	python -m src.memory.qdrant_retrieval

evaluate:
	python -m scripts.evaluate_playbook

week3: up
	@echo "Waiting 15 seconds for services to start..."
	@sleep 15
	$(MAKE) seed
	$(MAKE) run-crew
	$(MAKE) verify-langfuse
	$(MAKE) evaluate
	$(MAKE) test

publish-signal:
	python -m scripts.publish_signal

publish-port:
	python -m scripts.publish_signal --type port --severity 8

run-pipeline:
	python -m scripts.run_pipeline

run-pipeline-port:
	python -m scripts.run_pipeline --type port --severity 8

setup-aws:
	python -m scripts.setup_aws

week4: up
	@echo "Waiting 15 seconds for services to start..."
	@sleep 15
	$(MAKE) setup-aws
	$(MAKE) seed
	$(MAKE) run-pipeline
	$(MAKE) verify-langfuse
	$(MAKE) test

run-full-crew:
	python -m scripts.run_full_crew

run-full-crew-port:
	python -m scripts.run_full_crew --type port --severity 8

tune-debate:
	python -m scripts.tune_prompts --mode debate --runs 5

validate-debate:
	python -m scripts.tune_prompts --mode validate --runs 5

validate-prompts:
	python -m scripts.tune_prompts --mode validate --runs 3

week5: up
	@echo "Waiting 15 seconds for services to start..."
	@sleep 15
	$(MAKE) setup-aws
	$(MAKE) seed
	$(MAKE) run-full-crew-port
	$(MAKE) validate-prompts
	$(MAKE) verify-langfuse
	$(MAKE) test
