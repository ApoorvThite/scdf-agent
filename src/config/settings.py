from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field
from pydantic import ConfigDict


class LLMSettings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env", extra="ignore", protected_namespaces=()
    )

    openai_api_key: str = Field(..., validation_alias="OPENAI_API_KEY")
    helicone_api_key: str = Field(..., validation_alias="HELICONE_API_KEY")
    helicone_base_url: str = Field(
        "https://oai.helicone.ai/v1", validation_alias="HELICONE_BASE_URL"
    )
    model_primary: str = Field("gpt-4o-mini", validation_alias="MODEL_PRIMARY")
    model_debate: str = Field("gpt-4o", validation_alias="MODEL_DEBATE")
    model_fast: str = Field("gpt-4o-mini", validation_alias="MODEL_FAST")


class QdrantSettings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    host: str = Field("localhost", validation_alias="QDRANT_HOST")
    port: int = Field(6333, validation_alias="QDRANT_PORT")
    collection_disruptions: str = Field(
        "disruptions", validation_alias="QDRANT_COLLECTION_DISRUPTIONS"
    )
    collection_responses: str = Field(
        "responses", validation_alias="QDRANT_COLLECTION_RESPONSES"
    )
    collection_playbooks: str = Field(
        "playbooks", validation_alias="QDRANT_COLLECTION_PLAYBOOKS"
    )


class LangfuseSettings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    public_key: str = Field("", validation_alias="LANGFUSE_PUBLIC_KEY")
    secret_key: str = Field("", validation_alias="LANGFUSE_SECRET_KEY")
    host: str = Field("http://localhost:3000", validation_alias="LANGFUSE_HOST")


class RedisSettings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    url: str = Field("", validation_alias="UPSTASH_REDIS_URL")
    token: str = Field("", validation_alias="UPSTASH_REDIS_TOKEN")


class AWSSettings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    region: str = Field("us-east-1", validation_alias="AWS_REGION")
    access_key_id: str = Field("", validation_alias="AWS_ACCESS_KEY_ID")
    secret_access_key: str = Field("", validation_alias="AWS_SECRET_ACCESS_KEY")
    dynamodb_table_disruptions: str = Field(
        "scdf-disruptions", validation_alias="DYNAMODB_TABLE_DISRUPTIONS"
    )
    s3_bucket_playbooks: str = Field(
        "scdf-playbooks", validation_alias="S3_BUCKET_PLAYBOOKS"
    )
    sns_topic_critical: str = Field("", validation_alias="SNS_TOPIC_CRITICAL")
    sns_topic_standard: str = Field("", validation_alias="SNS_TOPIC_STANDARD")


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env", extra="ignore", protected_namespaces=()
    )

    project_name: str = Field("scdf-agent", validation_alias="PROJECT_NAME")
    environment: str = Field("development", validation_alias="ENVIRONMENT")
    log_level: str = Field("INFO", validation_alias="LOG_LEVEL")

    openai_api_key: str = Field(..., validation_alias="OPENAI_API_KEY")
    helicone_api_key: str = Field(..., validation_alias="HELICONE_API_KEY")
    helicone_base_url: str = Field(
        "https://oai.helicone.ai/v1", validation_alias="HELICONE_BASE_URL"
    )
    model_primary: str = Field("gpt-4o-mini", validation_alias="MODEL_PRIMARY")
    model_debate: str = Field("gpt-4o", validation_alias="MODEL_DEBATE")
    model_fast: str = Field("gpt-4o-mini", validation_alias="MODEL_FAST")

    qdrant_host: str = Field("localhost", validation_alias="QDRANT_HOST")
    qdrant_port: int = Field(6333, validation_alias="QDRANT_PORT")
    qdrant_collection_disruptions: str = Field(
        "disruptions", validation_alias="QDRANT_COLLECTION_DISRUPTIONS"
    )
    qdrant_collection_responses: str = Field(
        "responses", validation_alias="QDRANT_COLLECTION_RESPONSES"
    )
    qdrant_collection_playbooks: str = Field(
        "playbooks", validation_alias="QDRANT_COLLECTION_PLAYBOOKS"
    )

    langfuse_public_key: str = Field("", validation_alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field("", validation_alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(
        "http://localhost:3000", validation_alias="LANGFUSE_HOST"
    )

    upstash_redis_url: str = Field("", validation_alias="UPSTASH_REDIS_URL")
    upstash_redis_token: str = Field("", validation_alias="UPSTASH_REDIS_TOKEN")

    aws_region: str = Field("us-east-1", validation_alias="AWS_REGION")
    aws_access_key_id: str = Field("", validation_alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field("", validation_alias="AWS_SECRET_ACCESS_KEY")
    dynamodb_table_disruptions: str = Field(
        "scdf-disruptions", validation_alias="DYNAMODB_TABLE_DISRUPTIONS"
    )
    s3_bucket_playbooks: str = Field(
        "scdf-playbooks", validation_alias="S3_BUCKET_PLAYBOOKS"
    )
    sns_topic_critical: str = Field("", validation_alias="SNS_TOPIC_CRITICAL")
    sns_topic_standard: str = Field("", validation_alias="SNS_TOPIC_STANDARD")

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def llm(self) -> LLMSettings:
        return LLMSettings()

    @property
    def qdrant(self) -> QdrantSettings:
        return QdrantSettings()

    @property
    def langfuse(self) -> LangfuseSettings:
        return LangfuseSettings()

    @property
    def redis(self) -> RedisSettings:
        return RedisSettings()

    @property
    def aws(self) -> AWSSettings:
        return AWSSettings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance loaded from .env."""
    return Settings()
