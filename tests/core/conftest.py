from __future__ import annotations

from pathlib import Path

import pytest
from helpers import ConfigFactory

from gatehold.config import GateholdConfig


@pytest.fixture
def config_factory(tmp_path: Path) -> ConfigFactory:
    sequence = 0

    def make_config(**overrides: object) -> GateholdConfig:
        nonlocal sequence
        sequence += 1
        values: dict[str, object] = {
            "state_dir": tmp_path / f"state-{sequence}",
            "max_heavy_slots": 2,
            "cpu_limit_percent": 85,
            "memory_limit_percent": 85,
            "port_start": 55_000,
            "port_end": 55_010,
            "simulators": ("sim-a", "sim-b"),
        }
        values.update(overrides)
        return GateholdConfig.model_validate(values)

    return make_config
