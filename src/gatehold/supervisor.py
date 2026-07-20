"""Private process-group anchor for one managed Gatehold command."""

from __future__ import annotations

import os
import secrets
import select
import signal
import subprocess  # noqa: S404 - explicit argv, shell disabled.
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

ACTIVATION_TIMEOUT_SECONDS = 10.0
ACTIVATION_BYTE = b"1"
NOT_ACTIVATED_EXIT = 76
START_FAILED_EXIT = 127


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) < 4 or arguments[0] != "--result-file" or arguments[2] != "--":
        return 2
    result_path = Path(arguments[1])
    command = arguments[3:]
    if not command:
        return 2
    readable, _, _ = select.select(
        [sys.stdin.buffer],
        [],
        [],
        ACTIVATION_TIMEOUT_SECONDS,
    )
    if not readable or sys.stdin.buffer.read(1) != ACTIVATION_BYTE:
        return NOT_ACTIVATED_EXIT
    try:
        child = subprocess.Popen(  # noqa: S603 - literal argv, shell disabled.
            command,
            shell=False,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        return START_FAILED_EXIT
    exit_code = int(child.wait())
    _write_result(result_path, exit_code)
    while True:
        signal.pause()


def _write_result(path: Path, exit_code: int) -> None:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as result:
            result.write(str(exit_code))
            result.flush()
            os.fsync(result.fileno())
        temporary.replace(path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
