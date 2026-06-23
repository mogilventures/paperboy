"""Optional, conservative Sentry instrumentation for the backend.

Everything here no-ops unless ``SENTRY_DSN`` is set AND ``sentry-sdk`` is
installed, so the default deployment is unaffected. PII is stripped two ways:
``send_default_pii=False`` at init, and a ``before_send`` hook that drops the
``user`` and ``request`` contexts in case anything attaches them later. Tags and
context passed to :func:`capture_exception` are caller-controlled and must never
include secrets or full user-profile data.
"""
import os
from typing import Any, Optional

import logfire

_initialized = False


def _before_send(event: dict, hint: dict) -> Optional[dict]:
    """Strip user/request data before an event leaves the process."""
    event.pop("user", None)
    event.pop("request", None)
    contexts = event.get("contexts")
    if isinstance(contexts, dict):
        contexts.pop("request", None)
    return event


def init_sentry() -> bool:
    """Initialize Sentry if SENTRY_DSN is set. Safe to call more than once.

    Returns True when Sentry is active afterwards, False when it stays a no-op.
    """
    global _initialized
    if _initialized:
        return True

    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False

    try:
        import sentry_sdk
    except ImportError:
        logfire.warn("SENTRY_DSN is set but sentry-sdk is not installed; Sentry disabled")
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        # No performance tracing: we only want error reports here.
        traces_sample_rate=0.0,
        send_default_pii=False,
        # Stack-frame locals can contain user_info/prompts/secrets. Disable
        # them explicitly; send_default_pii does not cover local variables.
        include_local_variables=False,
        # Avoid request body capture even if a future integration attaches one.
        max_request_body_size="never",
        before_send=_before_send,
    )
    _initialized = True
    logfire.info("Sentry initialized")
    return True


def capture_exception(exc: BaseException, **tags: Any) -> None:
    """Report an exception to Sentry with tags. No-op unless initialized.

    Only pass non-sensitive scalar tags (stage, content_type, task_id). Never
    pass secrets, request bodies, or full user-profile data.
    """
    if not _initialized:
        return
    try:
        import sentry_sdk
    except ImportError:
        return

    # new_scope() (sentry-sdk 2.x) or push_scope() (1.x) — isolate the tags.
    scope_cm = getattr(sentry_sdk, "new_scope", None) or getattr(sentry_sdk, "push_scope")
    with scope_cm() as scope:
        for key, value in tags.items():
            if value is not None:
                scope.set_tag(key, str(value))
        sentry_sdk.capture_exception(exc)
