#!/bin/sh
set -eu

LABEL="io.github.endorfin.mcp-hub"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/mcp-hub.log"
SERVICE="mcp-hub.service"
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$SERVICE"
ROOT="$(cd "$(dirname "$0")" && pwd)"
URL="http://127.0.0.1:${PORT:-4747}"

usage() {
  echo "Usage: $0 install | uninstall | restart | status"
  echo
  echo "  install    Start the hub at login (and right now)."
  echo "  uninstall  Remove the autostart and stop the hub it started."
  echo "  restart    Restart the hub started by the autostart."
  echo "  status     Show whether the autostart is set up and the hub is running."
}

xml() {
  printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

hub_running() {
  python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)' "$URL/api/hub" 2>/dev/null
}

python_path() {
  python_bin="$(command -v python3 || true)"
  if [ -z "$python_bin" ]; then
    echo "python3 not found." >&2
    exit 1
  fi
}

refuse_second_hub() {
  if [ ! -f "$1" ] && hub_running; then
    echo "A hub is already running at $URL. Stop it first, then install." >&2
    exit 1
  fi
}

macos_install() {
  python_path
  refuse_second_hub "$PLIST"
  domain="gui/$(id -u)"
  launchctl bootout "$domain/$LABEL" 2>/dev/null || true
  mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "$python_bin")</string>
    <string>$(xml "$ROOT/app.py")</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$(xml "$ROOT")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$(xml "$PATH")</string>
    <key>PORT</key>
    <string>${PORT:-4747}</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$(xml "$LOG")</string>
  <key>StandardErrorPath</key>
  <string>$(xml "$LOG")</string>
</dict>
</plist>
EOF
  launchctl bootstrap "$domain" "$PLIST"
  echo "Autostart installed: $PLIST"
  echo "Hub: $URL  ·  Log: $LOG"
}

macos_uninstall() {
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Autostart removed."
}

macos_restart() {
  if [ ! -f "$PLIST" ]; then
    echo "Autostart is not set up." >&2
    exit 1
  fi
  launchctl kickstart -k "gui/$(id -u)/$LABEL"
  echo "Hub restarted."
}

linux_install() {
  python_path
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl not found – the autostart on Linux needs systemd." >&2
    exit 1
  fi
  refuse_second_hub "$UNIT"
  mkdir -p "$(dirname "$UNIT")"
  cat > "$UNIT" <<EOF
[Unit]
Description=MCP Hub
After=network.target

[Service]
ExecStart="$python_bin" "$ROOT/app.py"
WorkingDirectory=$ROOT
Environment="PATH=$PATH" "PORT=${PORT:-4747}"
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now "$SERVICE"
  echo "Autostart installed: $UNIT"
  echo "Hub: $URL  ·  Log: journalctl --user -u mcp-hub"
}

linux_uninstall() {
  systemctl --user disable --now "$SERVICE" 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload 2>/dev/null || true
  echo "Autostart removed."
}

linux_restart() {
  if [ ! -f "$UNIT" ]; then
    echo "Autostart is not set up." >&2
    exit 1
  fi
  systemctl --user restart "$SERVICE"
  echo "Hub restarted."
}

status() {
  if [ -f "$1" ]; then
    echo "Autostart: installed, $1"
  else
    echo "Autostart: not set up"
  fi
  if hub_running; then
    echo "Hub: running at $URL"
  else
    echo "Hub: not reachable"
  fi
}

case "$(uname -s)" in
  Darwin) platform=macos; unit_file="$PLIST" ;;
  Linux) platform=linux; unit_file="$UNIT" ;;
  *)
    echo "The autostart supports macOS (launchd) and Linux (systemd)." >&2
    exit 1
    ;;
esac

case "${1:-}" in
  install) "${platform}_install" ;;
  uninstall) "${platform}_uninstall" ;;
  restart) "${platform}_restart" ;;
  status) status "$unit_file" ;;
  *) usage; [ -n "${1:-}" ] && exit 1 || exit 0 ;;
esac
