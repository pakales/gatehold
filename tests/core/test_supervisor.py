from __future__ import annotations

import stat
from pathlib import Path

from gatehold.supervisor import _write_result  # pyright: ignore[reportPrivateUsage]


def test_result_write_replaces_destination_symlink_without_following_it(
    tmp_path: Path,
) -> None:
    external = tmp_path / "human-owned.txt"
    external.write_text("do not change", encoding="utf-8")
    result = tmp_path / "managed.exit"
    result.symlink_to(external)

    _write_result(result, 17)

    assert external.read_text(encoding="utf-8") == "do not change"
    assert not result.is_symlink()
    assert result.read_text(encoding="ascii") == "17"
    assert stat.S_IMODE(result.stat().st_mode) == 0o600


def test_result_write_leaves_no_predictable_temporary_file(
    tmp_path: Path,
) -> None:
    result = tmp_path / "managed.exit"

    _write_result(result, 0)

    assert result.read_text(encoding="ascii") == "0"
    assert [path.name for path in tmp_path.iterdir()] == ["managed.exit"]
