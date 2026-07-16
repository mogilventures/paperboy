from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
import os
from typing import Optional

class Settings(BaseSettings):
    """
    Centralized configuration for the Arxiv agent.
    All values are loaded from environment variables (or config/.env) with type safety.
    Missing mandatory fields will raise validation errors at startup.
    """
    # OpenAI key is no longer required at import time so a Fireworks-only
    # deployment can start without it. LLMClient enforces its presence when
    # LLM_PROVIDER=openai (the default), failing fast with a clear error.
    openai_api_key: Optional[str] = Field(default=None, validation_alias='OPENAI_API_KEY')
    openai_model: str = Field(default='gpt-4o', validation_alias='OPENAI_MODEL')

    # LLM provider selection (OpenAI-compatible). Keep OpenAI as the default.
    llm_provider: str = Field(
        default='openai',
        validation_alias='LLM_PROVIDER',
        description="Which LLM backend to use: 'openai' or 'fireworks'. Both use the OpenAI-compatible client.",
    )
    # API surface to call. When unset, the client picks a provider-appropriate
    # default: 'responses' for OpenAI, 'chat_completions' for Fireworks.
    llm_api_mode: Optional[str] = Field(
        default=None,
        validation_alias='LLM_API_MODE',
        description="LLM API surface: 'responses' or 'chat_completions'. Unset = provider default.",
    )

    # Fireworks AI (OpenAI-compatible endpoints). Only required when LLM_PROVIDER=fireworks.
    fireworks_api_key: Optional[str] = Field(
        default=None,
        validation_alias='FIREWORKS_API_KEY',
        description="Fireworks AI API key. Required only when LLM_PROVIDER=fireworks.",
    )
    fireworks_model: str = Field(
        default='accounts/fireworks/models/gpt-oss-120b',
        validation_alias='FIREWORKS_MODEL',
        description="Fireworks model id. Override with the model you want to evaluate.",
    )
    fireworks_base_url: str = Field(
        default='https://api.fireworks.ai/inference/v1',
        validation_alias='FIREWORKS_BASE_URL',
        description="Fireworks OpenAI-compatible base URL.",
    )
    top_n_articles: int = Field(default=5, validation_alias='TOP_N_ARTICLES')
    top_n_news: int = Field(default=5, validation_alias='TOP_N_NEWS', description="Number of news articles to include in digest")
    ranking_input_max_articles: int = Field(default=20, validation_alias='RANKING_INPUT_MAX_ARTICLES', description="Maximum number of raw articles to send to the LLM for the ranking step.")
    
    use_lightweight: bool = Field(default=True, validation_alias='USE_LIGHTWEIGHT', description="Use lightweight version without Playwright")

    # Email Template Feature Flag (Step 1: Python Templates)
    use_python_email_templates: bool = Field(
        default=True,
        validation_alias='USE_PYTHON_EMAIL_TEMPLATES',
        description='Render final digest via Jinja2 templates instead of LLM HTML generation'
    )

    # Email rendering options
    inline_email_css: bool = Field(
        default=True,
        validation_alias="INLINE_EMAIL_CSS",
        description="Inline CSS into rendered email HTML for better client compatibility"
    )
    feedback_cta_enabled: bool = Field(
        default=True,
        validation_alias="FEEDBACK_CTA_ENABLED",
        description="Show the temporary Tally feedback CTA in new digest HTML",
    )
    feedback_form_url: str = Field(
        default="https://tally.so/r/A7G02o",
        validation_alias="FEEDBACK_FORM_URL",
    )

    logfire_token: Optional[str] = Field(default=None, validation_alias='LOGFIRE_TOKEN', description="Logfire token for monitoring")

    # Sentry error monitoring (optional). No-ops when unset. PII is never sent.
    sentry_dsn: Optional[str] = Field(default=None, validation_alias='SENTRY_DSN', description="Sentry DSN for backend error reporting. Leave unset to disable.")
    sentry_environment: str = Field(default='production', validation_alias='SENTRY_ENVIRONMENT', description="Environment tag reported to Sentry")
    
    # News API Configuration
    newsapi_key: Optional[str] = Field(None, validation_alias='NEWSAPI_KEY')
    tavily_api_key: Optional[str] = Field(None, validation_alias='TAVILY_API_KEY')
    
    # News fetching parameters
    news_enabled: bool = Field(default=True, validation_alias='NEWS_ENABLED')
    news_max_articles: int = Field(default=50, validation_alias='NEWS_MAX_ARTICLES')
    news_max_extract: int = Field(default=10, validation_alias='NEWS_MAX_EXTRACT')  # Limit extraction
    news_language: str = Field(default='en', validation_alias='NEWS_LANGUAGE')
    news_sort_by: str = Field(default='relevancy', validation_alias='NEWS_SORT_BY')
    news_search_in: str = Field(default='title,description', validation_alias='NEWS_SEARCH_IN')
    news_sources: Optional[str] = Field(None, validation_alias='NEWS_SOURCES')  # Comma-separated
    news_exclude_domains: Optional[str] = Field(None, validation_alias='NEWS_EXCLUDE_DOMAINS')
    
    # Content extraction
    extract_max_concurrent: int = Field(default=3, validation_alias='EXTRACT_MAX_CONCURRENT')
    extract_timeout: int = Field(default=10, validation_alias='EXTRACT_TIMEOUT')
    
    # Rate limiting and delays
    ranking_delay: float = Field(default=0.3, validation_alias='RANKING_DELAY', description="Delay between ranking API calls in seconds")
    summary_delay: float = Field(default=0.3, validation_alias='SUMMARY_DELAY', description="Delay between summary API calls in seconds")
    summary_max_concurrent: int = Field(default=5, validation_alias='SUMMARY_MAX_CONCURRENT', description="Max concurrent summary generation")
    
    # Supabase Integration (essential for Cloud Run)
    supabase_url: Optional[str] = Field(None, validation_alias='SUPABASE_URL')
    supabase_key: Optional[str] = Field(None, validation_alias='SUPABASE_KEY')
    use_supabase: bool = Field(default=True, validation_alias='USE_SUPABASE', description="Use Supabase for distributed state management (recommended for Cloud Run)")
    supabase_service_role_key: Optional[str] = Field(
        None,
        validation_alias='SUPABASE_SERVICE_ROLE_KEY',
        description="Server-only Supabase key used by daily orchestration to access profiles",
    )

    # Backend-hosted daily orchestration (disabled until schema and secrets exist)
    orchestration_enabled: bool = Field(default=False, validation_alias='ORCHESTRATION_ENABLED')
    orchestration_hour_utc: int = Field(default=13, validation_alias='ORCHESTRATION_HOUR_UTC', ge=0, le=23)
    orchestration_poll_seconds: float = Field(default=60, validation_alias='ORCHESTRATION_POLL_SECONDS', gt=0)
    orchestration_catchup_hours: float = Field(default=24, validation_alias='ORCHESTRATION_CATCHUP_HOURS', gt=0)
    orchestration_profile_interval_seconds: float = Field(default=60, validation_alias='ORCHESTRATION_PROFILE_INTERVAL_SECONDS', ge=0)
    orchestration_max_concurrent_profiles: int = Field(default=2, validation_alias='ORCHESTRATION_MAX_CONCURRENT_PROFILES', gt=0)
    orchestration_stale_after_minutes: int = Field(default=120, validation_alias='ORCHESTRATION_STALE_AFTER_MINUTES', gt=0)
    resend_api_key: Optional[str] = Field(None, validation_alias='RESEND_API_KEY')
    resend_from_address: str = Field(
        default='Paperboy Digest <digest@paper-boy.app>',
        validation_alias='RESEND_FROM_ADDRESS',
    )
    # Sender identity for the signup welcome email (separate from the daily
    # digest sender). Must be a verified Resend sender on the same domain.
    welcome_from_address: str = Field(
        default='Welcome <hello@paper-boy.app>',
        validation_alias='WELCOME_FROM_ADDRESS',
    )

    # Caching
    news_cache_ttl: int = Field(default=3600, validation_alias='NEWS_CACHE_TTL')  # 1 hour
    
    # Monitoring configuration
    news_metrics_enabled: bool = Field(default=True, validation_alias='NEWS_METRICS_ENABLED')
    
    # Timeout configuration (critical for preventing timeouts)
    task_timeout: int = Field(default=600, validation_alias='TASK_TIMEOUT', description="Max time for fetch tasks in seconds")
    digest_task_timeout: int = Field(default=900, validation_alias='DIGEST_TASK_TIMEOUT', description="Max time for digest generation in seconds (independent of TASK_TIMEOUT, which can be a stale Fly secret)")
    request_timeout: int = Field(default=595, validation_alias='REQUEST_TIMEOUT', description="HTTP request timeout for API endpoints")
    http_timeout: int = Field(default=60, validation_alias='HTTP_TIMEOUT', description="General HTTP client timeout")
    
    @field_validator('newsapi_key', 'tavily_api_key')
    def validate_api_keys(cls, v, info):
        # Only validate if news is enabled and we're checking the keys
        if info.data.get('news_enabled', True) and not v:
            field_name = info.field_name
            # Only raise error if news is enabled but keys are missing
            import os
            if os.getenv('NEWS_ENABLED', 'true').lower() == 'true':
                print(f"Warning: {field_name} is not set but news_enabled=True")
        return v

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), '..', 'config', '.env'),
        env_file_encoding='utf-8',
        extra='ignore'
    )

settings = Settings() 