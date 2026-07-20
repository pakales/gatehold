"""Host pressure probes used by deterministic admission."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import psutil

from .models import HostSnapshot


class HostProbe(Protocol):
    def sample(
        self,
        *,
        cpu_limit_percent: float,
        memory_limit_percent: float,
        now: datetime,
    ) -> HostSnapshot: ...


class PsutilHostProbe:
    def sample(
        self,
        *,
        cpu_limit_percent: float,
        memory_limit_percent: float,
        now: datetime,
    ) -> HostSnapshot:
        cpu = float(psutil.cpu_percent(interval=None))
        memory = float(psutil.virtual_memory().percent)
        return HostSnapshot(
            sampled_at=now.astimezone(UTC),
            cpu_percent=cpu,
            memory_percent=memory,
            cpu_limit_percent=cpu_limit_percent,
            memory_limit_percent=memory_limit_percent,
            pressure_ok=cpu < cpu_limit_percent and memory < memory_limit_percent,
        )


class StaticHostProbe:
    """Deterministic probe for demos and tests."""

    def __init__(self, *, cpu_percent: float = 10, memory_percent: float = 20) -> None:
        self.cpu_percent = cpu_percent
        self.memory_percent = memory_percent

    def sample(
        self,
        *,
        cpu_limit_percent: float,
        memory_limit_percent: float,
        now: datetime,
    ) -> HostSnapshot:
        return HostSnapshot(
            sampled_at=now.astimezone(UTC),
            cpu_percent=self.cpu_percent,
            memory_percent=self.memory_percent,
            cpu_limit_percent=cpu_limit_percent,
            memory_limit_percent=memory_limit_percent,
            pressure_ok=(
                self.cpu_percent < cpu_limit_percent and self.memory_percent < memory_limit_percent
            ),
        )
