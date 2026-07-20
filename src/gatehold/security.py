"""Local daemon credential file handling."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from .privacy import new_secret


def ensure_daemon_token(path: Path) -> str:
    """Create or read a private bearer token without exposing it to logs."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        return read_daemon_token(path)

    token = new_secret()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, token.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    path.chmod(0o600)
    return token


def read_daemon_token(path: Path) -> str:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError("daemon token must be a regular file")
    path.chmod(0o600)
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("daemon token file is invalid")
    return token
