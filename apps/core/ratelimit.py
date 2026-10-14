"""
Rate limiting service for AERO-OPS (SIH26250) - Phase 1 Security Controls.
Uses Django cache framework with IP-based and user-based keys.
Enforces limits on sensitive endpoints:
- Login: 5/min per IP
- Registration: 5/min per IP
- Simulation Control: 20/min per user (or IP)
"""
from functools import wraps
from typing import Callable
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse


def get_client_ip(request: HttpRequest) -> str:
    """Extracts client IP considering standard reverse-proxy headers."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "127.0.0.1")


def check_rate_limit(
    request: HttpRequest,
    key_prefix: str,
    limit: int = 5,
    timeout: int = 60,
    by_user: bool = False,
) -> bool:
    """
    Returns True if request is allowed under rate limit, False if exceeded.
    Increments count in cache with the specified TTL window.
    """
    if by_user and request.user and request.user.is_authenticated:
        ident = f"user:{request.user.id}"
    else:
        ident = f"ip:{get_client_ip(request)}"

    cache_key = f"ratelimit:{key_prefix}:{ident}"
    count = cache.get(cache_key, 0)
    if count >= limit:
        return False
    cache.set(cache_key, count + 1, timeout=timeout)
    return True


def rate_limit_response(
    message: str = "Rate limit exceeded. Please wait before retrying.",
) -> JsonResponse:
    """Returns standard GovTech 429 Too Many Requests response."""
    return JsonResponse(
        {
            "error": message,
            "status": 429,
            "data_mode": "synthetic",
        },
        status=429,
    )


def ratelimit(
    key_prefix: str,
    limit: int = 5,
    timeout: int = 60,
    by_user: bool = False,
) -> Callable:
    """Decorator to enforce rate limiting on view functions."""
    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def _wrapped(request: HttpRequest, *args, **kwargs):
            if not check_rate_limit(
                request,
                key_prefix=key_prefix,
                limit=limit,
                timeout=timeout,
                by_user=by_user,
            ):
                return rate_limit_response(
                    f"Rate limit of {limit} requests per {timeout}s exceeded for {key_prefix}."
                )
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
