"""Validated local configuration and filesystem locations."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, field_validator

from .models import DomainModel

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT = 47_820


class GateholdConfig(DomainModel):
    state_dir: Path
    host: str = LOOPBACK_HOST
    daemon_port: int = Field(default=DEFAULT_DAEMON_PORT, ge=1024, le=65535)
    max_heavy_slots: int = Field(default=2, ge=1, le=2)
    cpu_limit_percent: float = Field(default=85, ge=1, le=100)
    memory_limit_percent: float = Field(default=85, ge=1, le=100)
    port_start: int = Field(default=49_152, ge=1024, le=65535)
    port_end: int = Field(default=49_251, ge=1024, le=65535)
    simulators: tuple[str, ...] = ()
    model: str = Field(default="gpt-5.6-sol", min_length=1, max_length=120)
    model_timeout_seconds: float = Field(default=12, gt=0, le=60)
    queue_ttl_seconds: int = Field(default=300, ge=60, le=3600)

    @field_validator("host")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        if value != LOOPBACK_HOST:
            raise ValueError("Gatehold may bind only to 127.0.0.1")
        return value

    @field_validator("port_end")
    @classmethod
    def valid_port_range(cls, value: int, info: object) -> int:
        data = getattr(info, "data", {})
        start = data.get("port_start")
        if isinstance(start, int) and value < start:
            raise ValueError("port_end must be greater than or equal to port_start")
        return value

    @property
    def database_path(self) -> Path:
        return self.state_dir / "gatehold.sqlite3"

    @property
    def token_path(self) -> Path:
        return self.state_dir / "daemon.token"

    @property
    def browser_profiles_dir(self) -> Path:
        return self.state_dir / "browser-profiles"

    @property
    def runtime_results_dir(self) -> Path:
        return self.state_dir / "runtime-results"

    @classmethod
    def from_environment(cls, *, state_dir: Path | None = None) -> GateholdConfig:
        selected_state = state_dir or Path(
            os.getenv("GATEHOLD_STATE_DIR") or Path.home() / ".gatehold"
        )
        simulators = tuple(
            value.strip()
            for value in os.getenv("GATEHOLD_SIMULATORS", "").split(",")
            if value.strip()
        )
        return cls(
            state_dir=selected_state.expanduser().resolve(),
            host=os.getenv("GATEHOLD_HOST", LOOPBACK_HOST),
            daemon_port=int(os.getenv("GATEHOLD_PORT", str(DEFAULT_DAEMON_PORT))),
            max_heavy_slots=int(os.getenv("GATEHOLD_MAX_HEAVY", "2")),
            cpu_limit_percent=float(os.getenv("GATEHOLD_CPU_LIMIT", "85")),
            memory_limit_percent=float(os.getenv("GATEHOLD_MEMORY_LIMIT", "85")),
            model=os.getenv("GATEHOLD_MODEL", "gpt-5.6-sol"),
            model_timeout_seconds=float(os.getenv("GATEHOLD_MODEL_TIMEOUT", "12")),
            queue_ttl_seconds=int(os.getenv("GATEHOLD_QUEUE_TTL", "300")),
            simulators=simulators,
        )
