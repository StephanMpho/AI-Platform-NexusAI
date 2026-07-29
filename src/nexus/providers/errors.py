"""Normalised provider errors.

This is the load-bearing part of the provider abstraction. Routing, retry and
fallback logic branch on these classes and must never branch on a provider's raw
error string — that is how a working fallback quietly stops working when a
provider rewords a message.

Each adapter is responsible for mapping its provider's failures onto these.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base for every normalised provider failure."""

    retryable: bool = False
    should_fallback: bool = False

    def __init__(self, message: str, *, provider: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code

    @property
    def error_class(self) -> str:
        """Stable string written to gateway_requests.error_class."""
        return {
            RateLimitError: "rate_limit",
            ProviderTimeoutError: "timeout",
            ContextLengthError: "context_length",
            ContentFilterError: "content_filter",
            AuthError: "auth",
            ProviderUnavailableError: "unavailable",
        }.get(type(self), "unknown")


class RateLimitError(ProviderError):
    """Retry the same model with backoff. Honour retry_after when present."""

    retryable = True
    should_fallback = True

    def __init__(self, message: str, *, provider: str, retry_after: float | None = None) -> None:
        super().__init__(message, provider=provider, status_code=429)
        self.retry_after = retry_after


class ProviderTimeoutError(ProviderError):
    """Fall back immediately. Retrying a timeout on the same model usually just
    spends the caller's latency budget twice."""

    should_fallback = True


class ProviderUnavailableError(ProviderError):
    """5xx or connection failure. Fall back."""

    should_fallback = True


class ContextLengthError(ProviderError):
    """Fall back only to a model with a larger context window, otherwise fail fast."""

    should_fallback = True


class ContentFilterError(ProviderError):
    """Never retry, never fall back. Another model will refuse it too, and
    quietly shopping a blocked prompt around providers is not a behaviour we want."""


class AuthError(ProviderError):
    """Never retry. A bad credential will still be bad in 200ms."""
