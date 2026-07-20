from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_install_local_wrapper_keeps_api_key_out_of_persistent_daemon(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    fake_bin = tmp_path / "fake-bin"
    fake_home = tmp_path / "home"
    argv_log = tmp_path / "uv-argv.log"
    env_log = tmp_path / "uv-env.log"
    fake_bin.mkdir()
    fake_home.mkdir()

    _write_executable(
        fake_bin / "uv",
        """#!/bin/sh
printf '%s\n' "$*" >> "$GATEHOLD_TEST_UV_ARGV_LOG"
if [ "${OPENAI_API_KEY+x}" = x ]; then
  printf 'present\n' >> "$GATEHOLD_TEST_UV_ENV_LOG"
else
  printf 'absent\n' >> "$GATEHOLD_TEST_UV_ENV_LOG"
fi
exit 0
""",
    )
    _write_executable(fake_bin / "launchctl", "#!/bin/sh\nexit 0\n")

    environment = os.environ.copy()
    environment.update(
        {
            "GATEHOLD_TEST_UV_ARGV_LOG": str(argv_log),
            "GATEHOLD_TEST_UV_ENV_LOG": str(env_log),
            "HOME": str(fake_home),
            "CODEX_HOME": str(fake_home / ".codex"),
            "OPENAI_API_KEY": "test-only-sentinel",
            "PATH": f"{fake_bin}:/usr/bin:/bin",
        }
    )
    subprocess.run(  # noqa: S603 - fixed trusted test-harness argv.
        ["/bin/bash", str(repo_root / "scripts" / "install-local.sh")],
        cwd=repo_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    wrapper = fake_home / ".local" / "bin" / "gatehold"
    wrapper_text = wrapper.read_text(encoding="utf-8")
    assert "--env-file" not in wrapper_text
    assert ".env.local" not in wrapper_text
    skill_link = fake_home / ".codex" / "skills" / "gatehold"
    assert skill_link.is_symlink()
    assert skill_link.readlink() == repo_root / "skills" / "gatehold"

    skill_link.unlink()
    skill_link.write_text("owned by another workflow\n", encoding="utf-8")
    blocked_install = subprocess.run(  # noqa: S603 - fixed trusted test-harness argv.
        ["/bin/bash", str(repo_root / "scripts" / "install-local.sh")],
        cwd=repo_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert blocked_install.returncode == 3
    assert "Refusing to replace an existing Gatehold skill" in blocked_install.stderr
    assert skill_link.read_text(encoding="utf-8") == "owned by another workflow\n"

    argv_log.unlink()
    env_log.unlink()
    subprocess.run(  # noqa: S603 - generated local wrapper under test.
        [str(wrapper), "daemon"],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    daemon_argv = argv_log.read_text(encoding="utf-8").splitlines()
    assert daemon_argv == [f"run --project {repo_root} gatehold daemon"]
    assert env_log.read_text(encoding="utf-8").splitlines() == ["absent"]
