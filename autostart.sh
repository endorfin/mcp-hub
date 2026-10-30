#!/bin/sh
set -eu

LABEL="de.tpwd.mcp-hub"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/mcp-hub.log"
ROOT="$(cd "$(dirname "$0")" && pwd)"
DOMAIN="gui/$(id -u)"
URL="http://127.0.0.1:${PORT:-4747}"

usage() {
  echo "Verwendung: $0 install | uninstall | restart | status"
  echo
  echo "  install    Hub beim Login starten (und jetzt sofort)."
  echo "  uninstall  Autostart entfernen und den so gestarteten Hub beenden."
  echo "  restart    Den per Autostart laufenden Hub neu starten."
  echo "  status     Zeigt, ob der Autostart eingerichtet ist und der Hub läuft."
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
    echo "python3 nicht gefunden." >&2
    exit 1
  fi
  if [ ! -f "$PLIST" ] && hub_running; then
    echo "Auf $URL läuft schon ein Hub. Erst beenden, dann einrichten." >&2
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
  echo "Autostart eingerichtet: $PLIST"
  echo "Hub: $URL  ·  Log: $LOG"
}

uninstall() {
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Autostart entfernt."
}

restart() {
  if [ ! -f "$PLIST" ]; then
    echo "Autostart ist nicht eingerichtet." >&2
    exit 1
  fi
  launchctl kickstart -k "$DOMAIN/$LABEL"
  echo "Hub neu gestartet."
}

status() {
  if [ -f "$PLIST" ]; then
    echo "Autostart: eingerichtet, $PLIST"
  else
    echo "Autostart: nicht eingerichtet"
  fi
  if hub_running; then
    echo "Hub: läuft auf $URL"
  else
    echo "Hub: nicht erreichbar"
  fi
}

case "${1:-}" in
  install) install ;;
  uninstall) uninstall ;;
  restart) restart ;;
  status) status ;;
  *) usage; [ -n "${1:-}" ] && exit 1 || exit 0 ;;
esac
