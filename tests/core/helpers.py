from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from gatehold.config import GateholdConfig


class MutableClock:
    def __init__(self, value: datetime | None = None) -> None:
        self.value = value or datetime(2026, 7, 20, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, *, seconds: float) -> datetime:
        self.value += timedelta(seconds=seconds)
        return self.value


ConfigFactory = Callable[..., GateholdConfig]
