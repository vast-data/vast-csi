"""
LRU Cache configuration for dogpile.cache with size limits.

This module provides:
- LRUMemoryBackend: A dogpile.cache backend with LRU eviction using cachetools.LRUCache
- cache_on_arguments: Wrapper for caching methods with **kwargs support
"""

from typing import Callable

from dogpile.cache import make_region
from dogpile.cache.util import kwarg_function_key_generator
from dogpile.cache.backends.memory import MemoryBackend
from dogpile.cache.backends.memory import NO_VALUE
from cachetools import LRUCache


class LRUMemoryBackend(MemoryBackend):
    """
    Memory backend with LRU eviction using cachetools.LRUCache.
    
    This backend adds size limits and LRU eviction to dogpile.cache's memory backend.
    When the cache reaches max_size, the least recently used item is evicted.
    
    Usage:
        region = make_region()
        region.backend = LRUMemoryBackend({'max_size': 500})
    """

    def __init__(self, arguments):
        self.NO_VALUE = NO_VALUE
        
        max_size = arguments.get("max_size", 200)
        self._cache = LRUCache(maxsize=max_size)

    def get(self, key):
        return self._cache.get(key, self.NO_VALUE)

    def set(self, key, value):
        self._cache[key] = value

    def delete(self, key):
        self._cache.pop(key, None)


# Create dogpile.cache region for method caching with LRU eviction (max 200 items)
_cache_region = make_region()
_cache_region.configure("dogpile.cache.memory")
_cache_region.backend = LRUMemoryBackend({"max_size": 200})


def cache_on_arguments(expiration_time: int):
    """
    Wrapper for cache_region.cache_on_arguments that uses kwarg_function_key_generator by default.
    This allows caching methods with **kwargs without specifying the key generator each time.
    
    Uses fn.__qualname__ as the cache namespace to prevent key collisions between
    different classes with the same method name (e.g. ViewPolicy.one vs VipPool.one).
    
    IMPORTANT: This decorator must be the INNERMOST (closest to the function definition)
    when used with other decorators like @requisite, @apiver, etc. Otherwise the key
    generator cannot properly inspect the function signature.
    
    Correct order:
        @requisite(semver="5.3.0")
        @apiver.v5
        @cache_on_arguments(expiration_time=5 * MINUTE)  # ← Innermost
        def get_subsystem(self, subsystem, **params):
            ...
    
    Args:
        expiration_time: Cache expiration time in seconds
        
    Returns:
        A decorator that can be applied to methods
        
    Example:
        @cache_on_arguments(expiration_time=5 * MINUTE)
        def get_subsystem(self, subsystem, **params):
            return self.one(name=subsystem, **params)
    """

    def wrapper(fn: Callable):
        namespace = fn.__qualname__

        return _cache_region.cache_on_arguments(
            namespace=namespace,
            expiration_time=expiration_time,
            function_key_generator=kwarg_function_key_generator
        )(fn)

    return wrapper
