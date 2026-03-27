"""Redis caching service for JAIGP."""
import redis
import json
from functools import wraps
from typing import Any, Optional
import config

# Initialize Redis client
redis_client = redis.Redis(
    host='localhost',
    port=6379,
    db=0,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=5
)

def check_redis_connection():
    """Check if Redis is available."""
    try:
        redis_client.ping()
        return True
    except redis.ConnectionError:
        return False

class CacheService:
    """Redis caching service."""

    @staticmethod
    def get(key: str) -> Optional[Any]:
        """Get value from cache."""
        if not check_redis_connection():
            return None

        try:
            value = redis_client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            print(f"Cache get error: {e}")
            return None

    @staticmethod
    def set(key: str, value: Any, timeout: int = 300):
        """Set value in cache with timeout (default 5 minutes)."""
        if not check_redis_connection():
            return False

        try:
            redis_client.setex(
                key,
                timeout,
                json.dumps(value, default=str)  # default=str handles datetime objects
            )
            return True
        except Exception as e:
            print(f"Cache set error: {e}")
            return False

    @staticmethod
    def delete(key: str):
        """Delete key from cache."""
        if not check_redis_connection():
            return False

        try:
            redis_client.delete(key)
            return True
        except Exception as e:
            print(f"Cache delete error: {e}")
            return False

    @staticmethod
    def clear_pattern(pattern: str):
        """Clear all keys matching pattern."""
        if not check_redis_connection():
            return False

        try:
            keys = redis_client.keys(pattern)
            if keys:
                redis_client.delete(*keys)
            return True
        except Exception as e:
            print(f"Cache clear error: {e}")
            return False

    @staticmethod
    def increment(key: str, amount: int = 1) -> Optional[int]:
        """Increment a counter."""
        if not check_redis_connection():
            return None

        try:
            return redis_client.incrby(key, amount)
        except Exception as e:
            print(f"Cache increment error: {e}")
            return None

    @staticmethod
    def set_expiry(key: str, seconds: int):
        """Set expiry time for a key."""
        if not check_redis_connection():
            return False

        try:
            redis_client.expire(key, seconds)
            return True
        except Exception as e:
            print(f"Cache expiry error: {e}")
            return False


def cache_result(key_prefix: str, timeout: int = 300):
    """
    Decorator to cache function results.

    Args:
        key_prefix: Prefix for cache key
        timeout: Cache timeout in seconds (default: 300 = 5 minutes)

    Usage:
        @cache_result("homepage", timeout=60)
        def get_homepage_papers():
            return db.query(Paper).limit(10).all()
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Skip caching if Redis is unavailable
            if not check_redis_connection():
                return func(*args, **kwargs)

            # Generate cache key from function arguments
            args_str = "_".join(str(arg) for arg in args if arg)
            kwargs_str = "_".join(f"{k}_{v}" for k, v in sorted(kwargs.items()) if v)
            cache_key = f"{key_prefix}:{args_str}:{kwargs_str}" if (args_str or kwargs_str) else key_prefix

            # Try to get from cache
            cached_value = CacheService.get(cache_key)
            if cached_value is not None:
                return cached_value

            # Execute function and cache result
            result = func(*args, **kwargs)
            CacheService.set(cache_key, result, timeout)

            return result
        return wrapper
    return decorator


# Rate limiting with Redis
class RateLimiter:
    """Redis-based rate limiter."""

    @staticmethod
    def check_rate_limit(identifier: str, limit: int = 120, window: int = 60) -> tuple[bool, int]:
        """
        Check if identifier has exceeded rate limit.

        Args:
            identifier: Unique identifier (e.g., IP address, user ID)
            limit: Maximum requests allowed
            window: Time window in seconds

        Returns:
            Tuple of (allowed: bool, remaining: int)
        """
        if not check_redis_connection():
            return (True, limit)  # Allow if Redis is down

        try:
            key = f"rate_limit:{identifier}"
            current = redis_client.get(key)

            if current is None:
                # First request
                redis_client.setex(key, window, 1)
                return (True, limit - 1)

            current_int = int(current)

            if current_int >= limit:
                # Limit exceeded
                return (False, 0)

            # Increment counter
            redis_client.incr(key)
            return (True, limit - current_int - 1)

        except Exception as e:
            print(f"Rate limit error: {e}")
            return (True, limit)  # Allow on error

    @staticmethod
    def reset_rate_limit(identifier: str):
        """Reset rate limit for identifier."""
        if not check_redis_connection():
            return False

        try:
            key = f"rate_limit:{identifier}"
            redis_client.delete(key)
            return True
        except Exception as e:
            print(f"Rate limit reset error: {e}")
            return False


# Initialize cache service
cache = CacheService()
rate_limiter = RateLimiter()

# Export
__all__ = ['cache', 'cache_result', 'rate_limiter', 'CacheService', 'RateLimiter']
