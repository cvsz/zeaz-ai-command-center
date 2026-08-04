#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

sandbox="$(mktemp -d)"
trap 'rm -rf "$sandbox"' EXIT
export HOME="$sandbox/home"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_STATE_HOME="$HOME/.local/state"
mkdir -p "$HOME"

app_dir="$HOME/.local/share/ai-cli-command-center"
bin_dir="$HOME/.local/bin"
config_dir="$XDG_CONFIG_HOME/ai-cli-command-center"
state_dir="$XDG_STATE_HOME/ai-cli-command-center"

./install.sh --host=127.0.0.1 --port=18765
[[ -x "$bin_dir/ai-cli-command-center" ]]
[[ -x "$bin_dir/ai-cli-command-center-gui" ]]
[[ -f "$app_dir/gui.py" && -f "$app_dir/version.py" ]]
"$bin_dir/ai-cli-command-center" --help >/dev/null

printf '\nLIFECYCLE_SENTINEL=preserved\n' >> "$config_dir/panel.env"
printf 'durable-state\n' > "$state_dir/sentinel"
printf 'old-install\n' > "$app_dir/upgrade-marker"

./install.sh --upgrade --host=127.0.0.1 --port=18765
[[ ! -e "$app_dir/upgrade-marker" ]]
grep -q 'LIFECYCLE_SENTINEL=preserved' "$config_dir/panel.env"
grep -q 'durable-state' "$state_dir/sentinel"
backup="$(find "$HOME/.local/share" -maxdepth 1 -type d -name 'ai-cli-command-center.backup-*' -print -quit)"
[[ -n "$backup" && -f "$backup/upgrade-marker" ]]
"$bin_dir/ai-cli-command-center" --help >/dev/null

"$app_dir/uninstall.sh"
[[ ! -e "$app_dir" ]]
[[ ! -e "$bin_dir/ai-cli-command-center" ]]
[[ ! -e "$bin_dir/ai-cli-command-center-gui" ]]
[[ -f "$config_dir/panel.env" ]]
[[ -f "$state_dir/sentinel" ]]

./install.sh --host=127.0.0.1 --port=18765
"$app_dir/uninstall.sh" --purge
[[ ! -e "$config_dir" ]]
[[ ! -e "$state_dir" ]]

echo "Install, upgrade, uninstall, and purge lifecycle passed."
