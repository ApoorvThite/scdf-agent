"""
pytest configuration — sets required environment variables for unit tests so
settings validation passes without a real .env file.
"""

import os
import pytest


@pytest.fixture(autouse=True)
def set_test_env(monkeypatch):
    """Inject stub API keys for tests that don't make real network calls."""
    env_vars = {
        "OPENAI_API_KEY": "sk-test-00000000000000000000000000000000",
        "HELICONE_API_KEY": "sk-helicone-test-0000000000000000000",
        "HELICONE_BASE_URL": "https://oai.helicone.ai/v1",
        "MODEL_PRIMARY": "gpt-4o-mini",
        "MODEL_DEBATE": "gpt-4o",
        "MODEL_FAST": "gpt-4o-mini",
        "QDRANT_HOST": "localhost",
        "QDRANT_PORT": "6333",
        "QDRANT_COLLECTION_DISRUPTIONS": "disruptions",
        "QDRANT_COLLECTION_RESPONSES": "responses",
        "QDRANT_COLLECTION_PLAYBOOKS": "playbooks",
        "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
        "LANGFUSE_SECRET_KEY": "sk-lf-test",
        "LANGFUSE_HOST": "http://localhost:3000",
        "UPSTASH_REDIS_URL": "",
        "UPSTASH_REDIS_TOKEN": "",
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "",
        "AWS_SECRET_ACCESS_KEY": "",
        "DYNAMODB_TABLE_DISRUPTIONS": "scdf-disruptions",
        "S3_BUCKET_PLAYBOOKS": "scdf-playbooks",
        "SNS_TOPIC_CRITICAL": "",
        "SNS_TOPIC_STANDARD": "",
        "PROJECT_NAME": "scdf-agent",
        "ENVIRONMENT": "development",
        "LOG_LEVEL": "INFO",
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)

    # Clear the settings cache so each test gets a fresh instance
    from src.config import settings as settings_module
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()
