"""Security middleware for JAIGP application."""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import time
from collections import defaultdict
from datetime import datetime, timedelta
from services.cache import rate_limiter

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Content Security Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-src 'self'; "
            "frame-ancestors 'self';"
        )

        # Prevent clickjacking from external sites (allow same-origin)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Enable XSS protection
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # Strict transport security (HSTS) - only if using HTTPS
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Redis-based rate limiting middleware to prevent abuse."""

    def __init__(self, app, requests_per_minute=120):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for static assets and lightweight poll endpoints
        path = request.url.path
        if (
            path.startswith("/static/")
            or path.endswith((".css", ".js", ".png", ".jpg", ".svg", ".ico", ".woff2"))
            or path.endswith("/feed/count")  # prompts/discussion polling
            or path.endswith("/thumbnail")   # paper thumbnails
        ):
            return await call_next(request)

        # Get real client IP (behind nginx reverse proxy)
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or request.headers.get("x-real-ip", "")
            or request.client.host
        )

        # Check rate limit using Redis
        allowed, remaining = rate_limiter.check_rate_limit(
            identifier=client_ip,
            limit=self.requests_per_minute,
            window=60  # 1 minute
        )

        if not allowed:
            return Response(
                content="Rate limit exceeded. Please try again later.",
                status_code=429,
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(self.requests_per_minute),
                    "X-RateLimit-Remaining": "0"
                }
            )

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response
