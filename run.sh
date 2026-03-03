#!/bin/bash
# Cinderella bot launcher.
# Usage: ./run.sh              — run in foreground
#        ./run.sh -d|--daemon  — run in background (survives terminal close)
#        ./run.sh --install    — install autorun (systemd/launchd), then start
#        ./run.sh --auto       — try autorun, else daemon, else foreground
#        ./run.sh --status     — check if running
#        ./run.sh --stop       — stop background process

set -e
cd "$(dirname "$0")"
ROOT="$PWD"
DATA="${ROOT}/data"
PIDFILE="${DATA}/cinderella.pid"
LOGFILE="${DATA}/cinderella.log"

# Use venv if present
if [ -d "venv" ]; then
    . venv/bin/activate
elif [ -d ".venv" ]; then
    . .venv/bin/activate
else
    echo "[>] Creating virtual environment..."
    python3 -m venv venv
    . venv/bin/activate
fi

echo "[>] Installing/updating dependencies..."
pip install -q -r requirements.txt

PYTHON="$(which python)"
mkdir -p "$DATA"

run_foreground() {
    echo "[>] Starting Cinderella (foreground)..."
    exec "$PYTHON" main.py
}

run_daemon() {
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "[!] Already running (PID $(cat "$PIDFILE"))"
        exit 1
    fi
    echo "[>] Starting Cinderella (background)..."
    nohup "$PYTHON" main.py >> "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "[+] Running in background. PID: $(cat "$PIDFILE")"
    echo "[>] Logs: $LOGFILE"
}

install_systemd_user() {
    UNIT_DIR="${HOME}/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    UNIT_FILE="${UNIT_DIR}/cinderella.service"
    cat > "$UNIT_FILE" << EOF
[Unit]
Description=Cinderella Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=$PYTHON $ROOT/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload 2>/dev/null || return 1
    systemctl --user enable cinderella.service 2>/dev/null || true
    systemctl --user start cinderella.service 2>/dev/null || return 1
    echo "[+] Installed systemd user service. Autorun on login."
    echo "[>] Commands: systemctl --user status cinderella | stop | start"
    return 0
}

install_launchd() {
    PLIST="${HOME}/Library/LaunchAgents/com.cinderella.bot.plist"
    mkdir -p "$(dirname "$PLIST")"
    cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cinderella.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$ROOT/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$ROOT</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF
    launchctl load "$PLIST" 2>/dev/null || return 1
    echo "[+] Installed launchd agent. Autorun on login."
    echo "[>] Commands: launchctl list | launchctl unload $PLIST"
    return 0
}

install_autorun() {
    echo "[>] Installing autorun..."
    if [[ "$(uname)" == "Linux" ]]; then
        if command -v systemctl &>/dev/null && systemctl --user 2>/dev/null; then
            install_systemd_user
        else
            echo "[!] systemd user mode not available. Use ./run.sh -d for background."
            return 1
        fi
    elif [[ "$(uname)" == "Darwin" ]]; then
        install_launchd
    else
        echo "[!] Autorun not supported on this OS. Use ./run.sh -d for background."
        return 1
    fi
}

do_status() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "[+] Running (PID $PID)"
        else
            echo "[!] PID file exists but process not running"
            rm -f "$PIDFILE"
        fi
    elif [[ "$(uname)" == "Linux" ]] && systemctl --user is-active cinderella 2>/dev/null | grep -q active; then
        echo "[+] Running (systemd user service)"
    elif [[ "$(uname)" == "Darwin" ]] && launchctl list 2>/dev/null | grep -q com.cinderella.bot; then
        echo "[+] Running (launchd)"
    else
        echo "[!] Not running"
    fi
}

do_stop() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            rm -f "$PIDFILE"
            echo "[+] Stopped (PID $PID)"
        else
            rm -f "$PIDFILE"
            echo "[!] Process already stopped"
        fi
    elif [[ "$(uname)" == "Linux" ]] && systemctl --user is-active cinderella 2>/dev/null | grep -q active; then
        systemctl --user stop cinderella
        echo "[+] Stopped (systemd)"
    elif [[ "$(uname)" == "Darwin" ]] && launchctl list 2>/dev/null | grep -q com.cinderella.bot; then
        launchctl unload "${HOME}/Library/LaunchAgents/com.cinderella.bot.plist"
        echo "[+] Stopped (launchd)"
    else
        echo "[!] Not running"
    fi
}

# Parse args
case "${1:-}" in
    -d|--daemon)
        run_daemon
        ;;
    --install)
        install_autorun || run_daemon
        ;;
    --auto)
        install_autorun && exit 0
        run_daemon && exit 0
        run_foreground
        ;;
    --status)
        do_status
        ;;
    --stop)
        do_stop
        ;;
    -h|--help)
        echo "Cinderella bot launcher"
        echo "  ./run.sh           Run in foreground"
        echo "  ./run.sh -d        Run in background"
        echo "  ./run.sh --install Install autorun (systemd/launchd) and start"
        echo "  ./run.sh --auto    Try autorun, else background, else foreground"
        echo "  ./run.sh --status  Check if running"
        echo "  ./run.sh --stop    Stop background process"
        ;;
    *)
        run_foreground
        ;;
esac
