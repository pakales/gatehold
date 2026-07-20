#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plist="${HOME}/Library/LaunchAgents/com.evlabs.gatehold.plist"
wrapper="${HOME}/.local/bin/gatehold"
skill_link="${CODEX_HOME:-${HOME}/.codex}/skills/gatehold"
skill_source="${repo_root}/skills/gatehold"

launchctl bootout "gui/${UID}/com.evlabs.gatehold" >/dev/null 2>&1 || true
rm -f "$plist" "$wrapper"
if [ -L "$skill_link" ] && [ "$(readlink "$skill_link")" = "$skill_source" ]; then
  rm "$skill_link"
fi

if [[ "${1:-}" == "--purge" ]]; then
  rm -rf "${HOME}/.gatehold"
  rm -rf "${HOME}/Library/Logs/Gatehold"
  echo "Gatehold and its local state were removed."
else
  echo "Gatehold was removed. Local receipts remain in ~/.gatehold."
fi
