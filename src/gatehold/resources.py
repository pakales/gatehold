"""Cooperative local runtime resource allocation."""

from __future__ import annotations

import socket
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection

from .config import GateholdConfig
from .models import ReasonCode, ResourceAllocation, ResourceRequest
from .privacy import new_secret, secret_digest
from .store import GateholdStore

PROFILE_MARKER_NAME = ".gatehold-profile-owner"


@dataclass(frozen=True, slots=True)
class ProfileProvenance:
    device: int
    inode: int
    marker_sha256: str


@dataclass(frozen=True, slots=True)
class AllocationAttempt:
    allocation: ResourceAllocation | None
    reasons: tuple[ReasonCode, ...]
    created_profile: Path | None = None
    profile_provenance: ProfileProvenance | None = None


class ResourceAllocator:
    def __init__(self, config: GateholdConfig, store: GateholdStore) -> None:
        self.config = config
        self.store = store

    def try_allocate(
        self,
        connection: Connection,
        *,
        request: ResourceRequest,
        lease_id: str,
    ) -> AllocationAttempt:
        reasons: list[ReasonCode] = []
        port: int | None = None
        simulator: str | None = None
        profile: Path | None = None
        profile_provenance: ProfileProvenance | None = None

        if request.port:
            allocated_ports = self.store.allocation_keys(connection, "port")
            port = next(
                (
                    candidate
                    for candidate in range(self.config.port_start, self.config.port_end + 1)
                    if str(candidate) not in allocated_ports and _port_is_available(candidate)
                ),
                None,
            )
            if port is None:
                reasons.append(ReasonCode.PORT_UNAVAILABLE)

        if request.simulator:
            allocated_simulators = self.store.allocation_keys(connection, "simulator")
            simulator = next(
                (
                    candidate
                    for candidate in self.config.simulators
                    if candidate not in allocated_simulators
                ),
                None,
            )
            if simulator is None:
                reasons.append(ReasonCode.SIMULATOR_UNAVAILABLE)

        if reasons:
            return AllocationAttempt(allocation=None, reasons=tuple(reasons))

        if request.browser_profile:
            try:
                profile = self.config.browser_profiles_dir / f"profile-{lease_id}"
                profile.mkdir(mode=0o700, parents=False, exist_ok=False)
                profile.chmod(0o700)
                marker = new_secret()
                marker_path = profile / PROFILE_MARKER_NAME
                marker_path.write_text(marker, encoding="utf-8")
                marker_path.chmod(0o600)
                info = profile.stat(follow_symlinks=False)
                profile_provenance = ProfileProvenance(
                    device=info.st_dev,
                    inode=info.st_ino,
                    marker_sha256=secret_digest(marker),
                )
            except OSError:
                if profile is not None:
                    marker_path = profile / PROFILE_MARKER_NAME
                    with suppress(OSError):
                        marker_path.unlink()
                    with suppress(OSError):
                        profile.rmdir()
                return AllocationAttempt(
                    allocation=None,
                    reasons=(ReasonCode.BROWSER_PROFILE_UNAVAILABLE,),
                )

        return AllocationAttempt(
            allocation=ResourceAllocation(
                port=port,
                browser_profile=str(profile) if profile is not None else None,
                simulator=simulator,
            ),
            reasons=(),
            created_profile=profile,
            profile_provenance=profile_provenance,
        )


def _port_is_available(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    finally:
        probe.close()
    return True
