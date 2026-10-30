#!/bin/sh
set -eu

LABEL="io.github.endorfin.mcp-hub"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/mcp-hub.log"
ROOT="$(cd "$(dirname "$0")" && pwd)"
DOMAIN="gui/$(id -u)"
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
  curl -fs -o /dev/null "$URL/api/hub"
}

install() {
  python_bin="$(command -v python3 || true)"
  if [ -z "$python_bin" ]; then
    echo "python3 not found." >&2
    exit 1
  fi
  if [ ! -f "$PLIST" ] && hub_running; then
    echo "A hub is already running at $URL. Stop it first, then install." >&2
    exit 1
  fi
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
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
  launchctl bootstrap "$DOMAIN" "$PLIST"
  echo "Autostart installed: $PLIST"
  echo "Hub: $URL  ·  Log: $LOG"
}

uninstall() {
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Autostart removed."
}

restart() {
  if [ ! -f "$PLIST" ]; then
    echo "Autostart is not set up." >&2
    exit 1
  fi
  launchctl kickstart -k "$DOMAIN/$LABEL"
  echo "Hub restarted."
}

status() {
  if [ -f "$PLIST" ]; then
    echo "Autostart: installed, $PLIST"
  else
    echo "Autostart: not set up"
  fi
  if hub_running; then
    echo "Hub: running at $URL"
  else
    echo "Hub: not reachable"
  fi
}

case "${1:-}" in
  install) install ;;
  uninstall) uninstall ;;
  restart) restart ;;
  status) status ;;
  *) usage; [ -n "${1:-}" ] && exit 1 || exit 0 ;;
esac
