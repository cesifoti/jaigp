"""Redis-backed session management for horizontal scaling."""
import json
import secrets
import time
from typing import Optional, Dict, Any
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send, Message
from services.cache import redis_client, check_redis_connection
import config


class RedisSessionBackend:
    """Redis-backed session storage."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.key = f"session:{session_id}"

    def get(self) -> Dict[str, Any]:
        """Get session data from Redis."""
        if not check_redis_connection():
            return {}
        try:
            data = redis_client.get(self.key)
            if data:
                return json.loads(data)
            return {}
        except Exception as e:
            print(f"Session get error: {e}")
            return {}

    def set(self, data: Dict[str, Any]) -> bool:
        """Save session data to Redis."""
        if not check_redis_connection():
            return False
        try:
            # Add metadata for debugging
            data_to_save = dict(data)
            data_to_save['_last_modified'] = time.time()
            data_to_save['_session_id'] = self.session_id[:8]  # First 8 chars for debugging

            redis_client.setex(
                self.key,
                config.SESSION_MAX_AGE,
                json.dumps(data_to_save, default=str)
            )
            return True
        except Exception as e:
            print(f"Session set error: {e}")
            return False

    def delete(self) -> bool:
        """Delete session from Redis."""
        if not check_redis_connection():
            return False
        try:
            redis_client.delete(self.key)
            return True
        except Exception as e:
            print(f"Session delete error: {e}")
            return False


class RedisSessionMiddleware:
    """Middleware for Redis-backed sessions with load balancing support."""

    def __init__(
        self,
        app: ASGIApp,
        session_cookie: str = "jaigp_session",
        max_age: int = 86400,
        https_only: bool = True,
        same_site: str = "lax"
    ):
        self.app = app
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.https_only = https_only
        self.same_site = same_site

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request with Redis session."""
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Get or create session ID from cookie
        session_id = None
        cookies = {}

        for header_name, header_value in scope.get("headers", []):
            if header_name == b"cookie":
                cookie_string = header_value.decode("latin-1")
                for cookie in cookie_string.split(";"):
                    if "=" in cookie:
                        name, value = cookie.strip().split("=", 1)
                        cookies[name] = value
                break

        session_id = cookies.get(self.session_cookie)

        # Validate session ID format (should be URL-safe base64)
        if session_id:
            # Basic validation - should be alphanumeric, -, _
            if not all(c.isalnum() or c in '-_' for c in session_id):
                session_id = None
            # Reasonable length check (should be around 43 chars for 32 bytes)
            elif len(session_id) < 20 or len(session_id) > 100:
                session_id = None

        if not session_id:
            session_id = secrets.token_urlsafe(32)

        # Load session data
        backend = RedisSessionBackend(session_id)
        session_data = backend.get()

        # Create session object - CRITICAL: Use a copy to prevent cross-request contamination
        scope["session"] = dict(session_data.copy())

        async def send_wrapper(message: Message) -> None:
            """Wrap send to save session data."""
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)

                # Check if session was cleared (logout)
                if not scope["session"]:
                    # Delete session from Redis
                    backend.delete()

                    # Expire the cookie by setting Max-Age to 0
                    cookie_value = f"{self.session_cookie}={session_id}; "
                    cookie_value += f"Max-Age=0; "
                    cookie_value += f"Path=/; "
                    cookie_value += f"SameSite={self.same_site}; "
                    cookie_value += "HttpOnly; "
                    if self.https_only:
                        cookie_value += "Secure; "

                    headers.append("Set-Cookie", cookie_value.rstrip("; "))
                else:
                    # Save session data
                    backend.set(scope["session"])

                    # Set session cookie
                    cookie_value = f"{self.session_cookie}={session_id}; "
                    cookie_value += f"Max-Age={self.max_age}; "
                    cookie_value += f"Path=/; "
                    cookie_value += f"SameSite={self.same_site}; "
                    cookie_value += "HttpOnly; "
                    if self.https_only:
                        cookie_value += "Secure; "

                    headers.append("Set-Cookie", cookie_value.rstrip("; "))

            await send(message)

        await self.app(scope, receive, send_wrapper)
