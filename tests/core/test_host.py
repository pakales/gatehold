from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from gatehold.host import PsutilHostProbe


def test_psutil_probe_uses_bounded_interval_for_meaningful_first_cpu_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intervals: list[float | None] = []

    def sample_cpu(interval: float | None = None) -> float:
        intervals.append(interval)
        return 91

    monkeypatch.setattr("gatehold.host.psutil.cpu_percent", sample_cpu)
    monkeypatch.setattr(
        "gatehold.host.psutil.virtual_memory",
        lambda: SimpleNamespace(percent=24),
    )

    snapshot = PsutilHostProbe(sample_interval_seconds=0.05).sample(
        cpu_limit_percent=85,
        memory_limit_percent=85,
        now=datetime(2026, 7, 20, tzinfo=UTC),
    )

    assert intervals == [0.05]
    assert snapshot.cpu_percent == 91
    assert snapshot.memory_percent == 24
    assert snapshot.pressure_ok is False


def test_psutil_probe_preserves_memory_pressure_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def sample_cpu(interval: float | None = None) -> float:
        assert interval is not None
        return 12

    monkeypatch.setattr("gatehold.host.psutil.cpu_percent", sample_cpu)
    monkeypatch.setattr(
        "gatehold.host.psutil.virtual_memory",
        lambda: SimpleNamespace(percent=92),
    )

    snapshot = PsutilHostProbe().sample(
        cpu_limit_percent=85,
        memory_limit_percent=85,
        now=datetime(2026, 7, 20, tzinfo=UTC),
    )

    assert snapshot.cpu_percent == 12
    assert snapshot.memory_percent == 92
    assert snapshot.pressure_ok is False


@pytest.mark.parametrize("interval", [0, 0.049, 1.001])
def test_psutil_probe_rejects_non_meaningful_or_excessive_intervals(
    interval: float,
) -> None:
    with pytest.raises(ValueError, match="sample_interval_seconds"):
        PsutilHostProbe(sample_interval_seconds=interval)
