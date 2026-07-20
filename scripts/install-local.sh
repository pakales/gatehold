#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin_dir="${HOME}/.local/bin"
wrapper="${bin_dir}/gatehold"
codex_home="${CODEX_HOME:-${HOME}/.codex}"
skills_dir="${codex_home}/skills"
skill_source="${repo_root}/skills/gatehold"
skill_link="${skills_dir}/gatehold"
launch_agents="${HOME}/Library/LaunchAgents"
plist="${launch_agents}/com.evlabs.gatehold.plist"
logs="${HOME}/Library/Logs/Gatehold"

command -v uv >/dev/null 2>&1 || {
  echo "Gatehold requires uv: https://docs.astral.sh/uv/" >&2
  exit 2
}
uv_path="$(command -v uv)"

if [ -L "$skill_link" ]; then
  if [ "$(readlink "$skill_link")" != "$skill_source" ]; then
    echo "Refusing to replace an existing Gatehold skill link: $skill_link" >&2
    exit 3
  fi
elif [ -e "$skill_link" ]; then
  echo "Refusing to replace an existing Gatehold skill: $skill_link" >&2
  exit 3
fi

cd "$repo_root"
uv sync --all-groups --locked

mkdir -p "$bin_dir" "$skills_dir" "$launch_agents" "$logs"

wrapper_tmp="$(mktemp "${wrapper}.XXXXXX")"
cat >"$wrapper_tmp" <<EOF
#!/bin/sh
if [ "\${1:-}" = "daemon" ]; then
  unset OPENAI_API_KEY
fi
exec "$uv_path" run --project "$repo_root" gatehold "\$@"
EOF
chmod 0755 "$wrapper_tmp"
mv "$wrapper_tmp" "$wrapper"

if [ ! -L "$skill_link" ]; then
  ln -s "$skill_source" "$skill_link"
fi

plist_tmp="$(mktemp "${plist}.XXXXXX")"
cat >"$plist_tmp" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.evlabs.gatehold</string>
  <key>ProgramArguments</key>
  <array>
    <string>$wrapper</string>
    <string>daemon</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>$logs/daemon.log</string>
  <key>StandardErrorPath</key>
  <string>$logs/daemon-error.log</string>
</dict>
</plist>
EOF
chmod 0644 "$plist_tmp"
mv "$plist_tmp" "$plist"

"$wrapper" init >/dev/null

launchctl bootout "gui/${UID}/com.evlabs.gatehold" >/dev/null 2>&1 || true
launchctl bootstrap "gui/${UID}" "$plist"

echo "Gatehold installed. Daemon health: http://127.0.0.1:47820/healthz"
echo "Codex skill linked at: $skill_link"
