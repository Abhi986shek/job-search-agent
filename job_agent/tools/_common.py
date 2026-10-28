"""Helpers shared by the @tool modules."""

from __future__ import annotations

import json
from typing import Any, Coroutine, TypeVar

from utils import run_coro_sync

T = TypeVar("T")


def run(coro: Coroutine[Any, Any, T]) -> T:
    """Strands calls tools synchronously from a worker thread; services are async."""
    return run_coro_sync(coro)


def jsonable(value: Any) -> Any:
    """Make dates and other values JSON-safe for the model."""
    return json.loads(json.dumps(value, default=str))
