#!/usr/bin/env bash
set -euo pipefail

plist="${HOME}/Library/LaunchAgents/com.evlabs.gatehold.plist"
wrapper="${HOME}/.local/bin/gatehold"

launchctl bootout "gui/${UID}/com.evlabs.gatehold" >/dev/null 2>&1 || true
rm -f "$plist" "$wrapper"

if [[ "${1:-}" == "--purge" ]]; then
  rm -rf "${HOME}/.gatehold"
  rm -rf "${HOME}/Library/Logs/Gatehold"
  echo "Gatehold and its local state were removed."
else
  echo "Gatehold was removed. Local receipts remain in ~/.gatehold."
fi
