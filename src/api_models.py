from datetime import date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, HttpUrl, Field
from .models import UserContext


class SupabaseWebhookRecord(BaseModel):
    """The inserted ``profiles`` row carried by a Supabase database webhook."""
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = None
    user_id: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None


class SupabaseWebhookPayload(BaseModel):
    """Payload shape emitted by a Supabase ``INSERT`` database webhook.

    See https://supabase.com/docs/guides/database/webhooks. Only ``record`` is
    needed here; other fields are accepted and ignored.
    """
    model_config = ConfigDict(extra="ignore")
    type: Optional[str] = None
    table: Optional[str] = None
    record: Optional[SupabaseWebhookRecord] = None

class GenerateDigestRequest(BaseModel):
    """Request model for generating a digest."""
    user_info: UserContext
    target_date: Optional[str] = None
    top_n_articles: Optional[int] = None
    top_n_news: Optional[int] = None
    callback_url: Optional[HttpUrl] = None
    categories: List[str] = Field(default=["cs.AI", "cs.LG"])
    digest_sources: Optional[Dict[str, bool]] = Field(
        default=None,
        description="Control which sources to include in digest generation. Defaults to all enabled sources if not specified."
    )
    source_date: Optional[str] = Field(
        default=None,
        description="Date of pre-fetched sources to use for digest generation (YYYY-MM-DD). If not provided, uses latest available sources."
    )

class GenerateDigestResponse(BaseModel):
    """Response model for the digest generation request."""
    task_id: str
    status: str
    message: str
    status_url: Optional[str] = None

class DigestStatusResponse(BaseModel):
    """Response model for checking digest generation status."""
    task_id: str
    status: str  # "pending", "processing", "completed", "failed"
    message: str  # Status message
    result: Optional[str] = None
    error: Optional[str] = None
    callback_url: Optional[str] = None
    articles: Optional[List[Dict[str, Any]]] = None

class FetchSourcesRequest(BaseModel):
    """Request model for fetching daily sources."""
    source_date: str = Field(
        description="Date to fetch sources for in YYYY-MM-DD format"
    )
    callback_url: Optional[HttpUrl] = Field(
        default=None,
        description="Optional callback URL for async completion notification"
    )

class FetchSourcesResponse(BaseModel):
    """Response model for fetch sources request."""
    task_id: str
    status: str
    message: str
    source_date: str
    status_url: Optional[str] = None

class OrchestrationRunRequest(BaseModel):
    """Request a durable daily run without a UI."""

    source_date: Optional[date] = Field(
        default=None,
        description="Source date to process; defaults to yesterday in UTC",
    )
    retry_failed: bool = Field(
        default=False,
        description="Reclaim a failed/partial run; sent deliveries remain skipped",
    )


class OrchestrationRunResponse(BaseModel):
    source_date: date
    status: str


class FetchStatusResponse(BaseModel):
    """Response model for checking fetch task status."""
    task_id: str
    status: str  # "pending", "processing", "completed", "failed"
    message: str
    source_date: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    callback_url: Optional[str] = None 