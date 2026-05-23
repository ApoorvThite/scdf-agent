.PHONY: install up down setup seed test signal week1 run-crew run-crew-port verify-langfuse week2

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
