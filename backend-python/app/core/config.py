from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    server_host: str = "0.0.0.0"
    server_port: int = 8080

    db_url: str = Field(
        "jdbc:mysql://127.0.0.1:3306/db_deep_research?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai",
        alias="DB_URL",
    )
    db_username: str = Field("root", alias="DB_USERNAME")
    db_password: str = Field("12345678", alias="DB_PASSWORD")

    redis_host: str = Field("127.0.0.1", alias="REDIS_HOST")
    redis_port: int = Field(6379, alias="REDIS_PORT")
    redis_password: str = Field("", alias="REDIS_PASSWORD")
    redis_database: int = Field(0, alias="REDIS_DATABASE")

    tavily_api_key: str = Field("", alias="TAVILY_API_KEY")
    tavily_base_url: str = Field("https://api.tavily.com", alias="TAVILY_BASE_URL")
    tavily_cache_enabled: bool = Field(True, alias="TAVILY_CACHE_ENABLED")
    tavily_cache_ttl_minutes: int = Field(60, alias="TAVILY_CACHE_TTL_MINUTES")
    tavily_cache_max_entries: int = Field(512, alias="TAVILY_CACHE_MAX_ENTRIES")

    research_search_max_results_per_query: int = Field(3, alias="RESEARCH_SEARCH_MAX_RESULTS_PER_QUERY")
    research_search_summary_timeout_seconds: int = Field(60, alias="RESEARCH_SEARCH_SUMMARY_TIMEOUT_SECONDS")
    research_search_summary_raw_content_max_chars: int = Field(12000, alias="RESEARCH_SEARCH_SUMMARY_RAW_CONTENT_MAX_CHARS")
    research_search_summary_fallback_content_max_chars: int = Field(1200, alias="RESEARCH_SEARCH_SUMMARY_FALLBACK_CONTENT_MAX_CHARS")
    research_search_summary_cache_enabled: bool = Field(True, alias="RESEARCH_SEARCH_SUMMARY_CACHE_ENABLED")
    research_search_summary_cache_ttl_minutes: int = Field(60, alias="RESEARCH_SEARCH_SUMMARY_CACHE_TTL_MINUTES")
    research_search_summary_cache_max_entries: int = Field(1024, alias="RESEARCH_SEARCH_SUMMARY_CACHE_MAX_ENTRIES")
    research_report_findings_max_chars: int = Field(20000, alias="RESEARCH_REPORT_FINDINGS_MAX_CHARS")

    jwt_secret: str = Field("deep-research-jwt-secret-key-must-be-at-least-32-chars", alias="JWT_SECRET")
    jwt_expiration_minutes: int = Field(10080, alias="JWT_EXPIRATION")

    app_time_zone: str = Field("Asia/Shanghai", alias="APP_TIME_ZONE")
    research_agent_framework: str = Field("agentscope-python", alias="RESEARCH_AGENT_FRAMEWORK")
    llm_timeout: int = Field(300, alias="LLM_TIMEOUT")

    research_async_max_pool_size: int = Field(10, alias="RESEARCH_ASYNC_MAX_POOL_SIZE")
    research_async_queue_capacity: int = Field(50, alias="RESEARCH_ASYNC_QUEUE_CAPACITY")
    research_async_task_timeout_minutes: int = Field(3, alias="RESEARCH_ASYNC_TASK_TIMEOUT_MINUTES")

    research_observability_enabled: bool = Field(False, alias="RESEARCH_OBSERVABILITY_ENABLED")
    research_observability_provider: str = Field("none", alias="RESEARCH_OBSERVABILITY_PROVIDER")
    research_observability_endpoint: str = Field("", alias="RESEARCH_OBSERVABILITY_ENDPOINT")
    research_observability_capture_io: bool = Field(False, alias="RESEARCH_OBSERVABILITY_CAPTURE_IO")
    research_observability_io_max_chars: int = Field(500, alias="RESEARCH_OBSERVABILITY_IO_MAX_CHARS")
    langfuse_public_key: str = Field("", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field("", alias="LANGFUSE_SECRET_KEY")
    langfuse_ingestion_version: str = Field("4", alias="LANGFUSE_INGESTION_VERSION")

    budget_medium_max_conduct_count: int = Field(2, alias="BUDGET_MEDIUM_MAX_CONDUCT_COUNT")
    budget_medium_max_search_count: int = Field(2, alias="BUDGET_MEDIUM_MAX_SEARCH_COUNT")
    budget_medium_max_concurrent_units: int = Field(1, alias="BUDGET_MEDIUM_MAX_CONCURRENT_UNITS")
    budget_high_max_conduct_count: int = Field(4, alias="BUDGET_HIGH_MAX_CONDUCT_COUNT")
    budget_high_max_search_count: int = Field(3, alias="BUDGET_HIGH_MAX_SEARCH_COUNT")
    budget_high_max_concurrent_units: int = Field(2, alias="BUDGET_HIGH_MAX_CONCURRENT_UNITS")
    budget_ultra_max_conduct_count: int = Field(6, alias="BUDGET_ULTRA_MAX_CONDUCT_COUNT")
    budget_ultra_max_search_count: int = Field(4, alias="BUDGET_ULTRA_MAX_SEARCH_COUNT")
    budget_ultra_max_concurrent_units: int = Field(3, alias="BUDGET_ULTRA_MAX_CONCURRENT_UNITS")

    def sqlalchemy_url(self) -> str:
        if self.db_url.startswith("jdbc:mysql://"):
            raw = self.db_url.removeprefix("jdbc:")
            parsed = urlparse(raw)
            query = parse_qs(parsed.query)
            charset = query.get("characterEncoding", ["utf8mb4"])[0]
            if charset.lower() == "utf8":
                charset = "utf8mb4"
            user = quote_plus(self.db_username)
            password = quote_plus(self.db_password)
            return f"mysql+aiomysql://{user}:{password}@{parsed.hostname}:{parsed.port or 3306}{parsed.path}?charset={charset}"
        return self.db_url

    def redis_url(self) -> str:
        auth = f":{quote_plus(self.redis_password)}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_database}"

    def budget_levels(self) -> dict[str, "BudgetLevel"]:
        return {
            "MEDIUM": BudgetLevel(
                max_conduct_count=self.budget_medium_max_conduct_count,
                max_search_count=self.budget_medium_max_search_count,
                max_concurrent_units=self.budget_medium_max_concurrent_units,
            ),
            "HIGH": BudgetLevel(
                max_conduct_count=self.budget_high_max_conduct_count,
                max_search_count=self.budget_high_max_search_count,
                max_concurrent_units=self.budget_high_max_concurrent_units,
            ),
            "ULTRA": BudgetLevel(
                max_conduct_count=self.budget_ultra_max_conduct_count,
                max_search_count=self.budget_ultra_max_search_count,
                max_concurrent_units=self.budget_ultra_max_concurrent_units,
            ),
        }


class BudgetLevel:
    def __init__(self, max_conduct_count: int, max_search_count: int, max_concurrent_units: int) -> None:
        self.max_conduct_count = max_conduct_count
        self.max_search_count = max_search_count
        self.max_concurrent_units = max_concurrent_units


@lru_cache
def get_settings() -> Settings:
    return Settings()
