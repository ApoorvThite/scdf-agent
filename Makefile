.PHONY: install up down setup seed test signal week1

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
