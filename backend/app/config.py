from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str
    database_url: SecretStr
    anthropic_api_key: SecretStr | None = None
    anthropic_api_url: str = "https://api.anthropic.com/v1/messages"
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_api_version: str = "2023-06-01"
    bhashini_api_key: SecretStr | None = None
    bhashini_user_id: str | None = None
    bhashini_api_url: str = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
    jwt_signing_key: SecretStr
    credential_kek_secret_resource: str
    voyage_api_key: SecretStr | None = None
    cohere_api_key: SecretStr | None = None
    voyage_api_url: str
    voyage_model: str
    cohere_api_url: str = "https://api.cohere.com/v2/rerank"
    cohere_model: str = "rerank-v3.5"
    min_relevance: float = 0.35
    weak_reranker_score: float = 0.35
    high_confidence_reranker_score: float = 0.65
    agentic_timeout_seconds: float = 30.0
    qa_retention_days: int = 90
    ask_rate_limit_per_minute: int = 30
    retrieve_rate_limit_per_minute: int = 60
    classification_tree_path: str | None = None
    otel_service_name: str
    otel_exporter_otlp_endpoint: str
    otel_traces_exporter: str
    otel_metrics_exporter: str = "otlp"
    otel_metric_export_interval_ms: int = 15000
    deployment_environment: str = "development"
    service_version: str = "0.1.0"
    allowed_origins: list[str] = Field(default_factory=list)
    trusted_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "testserver", "backend"])
    notification_provider: str = "logging"
    notification_webhook_url: SecretStr | None = None
    rate_limit_backend: str = "memory"
    allow_stub_connectors: bool = False
    max_request_body_bytes: int = 9_000_000

    @model_validator(mode="after")
    def production_guardrails(self) -> "Settings":
        if self.deployment_environment not in {"development", "test", "staging", "production"}:
            raise ValueError("DEPLOYMENT_ENVIRONMENT must be development, test, staging, or production")
        if self.deployment_environment == "production":
            if self.notification_provider != "webhook" or self.notification_webhook_url is None:
                raise ValueError("production requires NOTIFICATION_PROVIDER=webhook and NOTIFICATION_WEBHOOK_URL")
            if self.rate_limit_backend != "gateway":
                raise ValueError("production requires RATE_LIMIT_BACKEND=gateway (enforced at the edge)")
            if not self.allowed_origins or "*" in self.allowed_origins:
                raise ValueError("production requires explicit ALLOWED_ORIGINS")
            if not self.trusted_hosts or "*" in self.trusted_hosts:
                raise ValueError("production requires explicit TRUSTED_HOSTS")
            signing_key = self.jwt_signing_key.get_secret_value()
            if len(signing_key) < 32 or "test" in signing_key.lower():
                raise ValueError("production JWT_SIGNING_KEY must be at least 32 characters")
            if self.allow_stub_connectors:
                raise ValueError("production cannot enable stub connectors")
        if not 1_024 <= self.max_request_body_bytes <= 10_000_000:
            raise ValueError("MAX_REQUEST_BODY_BYTES must be between 1024 and 10000000")
        if not 0 <= self.weak_reranker_score <= self.high_confidence_reranker_score <= 1:
            raise ValueError("reranker confidence thresholds must satisfy 0 <= weak <= high <= 1")
        return self

    model_config = SettingsConfigDict(case_sensitive=False, extra="forbid")


@lru_cache
def get_settings() -> Settings:
    return Settings()
