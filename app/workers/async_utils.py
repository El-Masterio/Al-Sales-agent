"""
app/workers/async_utils.py
==========================
Bridge for running async service code from within synchronous Celery tasks.

Celery tasks are synchronous, but all our services are async. This module
provides `run_async` which manages an event loop per worker process so we
can call `await`-based services without spinning up a new loop every call
(which would break the asyncpg connection pool).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run_async(coro: Coroutine[None, None, T]) -> T:
    """Run an async coroutine to completion from a sync Celery task."""
    loop = _get_loop()
    return loop.run_until_complete(coro)
