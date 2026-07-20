"""Host pressure probes used by deterministic admission."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import psutil

from .models import HostSnapshot

DEFAULT_CPU_SAMPLE_INTERVAL_SECONDS = 0.1
MIN_CPU_SAMPLE_INTERVAL_SECONDS = 0.05
MAX_CPU_SAMPLE_INTERVAL_SECONDS = 1.0


class HostProbe(Protocol):
    def sample(
        self,
        *,
        cpu_limit_percent: float,
        memory_limit_percent: float,
        now: datetime,
    ) -> HostSnapshot: ...


class PsutilHostProbe:
    def __init__(
        self,
        *,
        sample_interval_seconds: float = DEFAULT_CPU_SAMPLE_INTERVAL_SECONDS,
    ) -> None:
        if not (
            MIN_CPU_SAMPLE_INTERVAL_SECONDS
            <= sample_interval_seconds
            <= MAX_CPU_SAMPLE_INTERVAL_SECONDS
        ):
            raise ValueError(
                "sample_interval_seconds must be between "
                f"{MIN_CPU_SAMPLE_INTERVAL_SECONDS} and "
                f"{MAX_CPU_SAMPLE_INTERVAL_SECONDS}"
            )
        self.sample_interval_seconds = sample_interval_seconds

    def sample(
        self,
        *,
        cpu_limit_percent: float,
        memory_limit_percent: float,
        now: datetime,
    ) -> HostSnapshot:
        # A non-blocking first psutil sample is relative to process-local
        # history and commonly returns a meaningless 0.0 in short-lived CLIs.
        cpu = float(psutil.cpu_percent(interval=self.sample_interval_seconds))
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
