#!/usr/bin/env bash
# Install iPracticom Sweeper as a systemd service + timer.
#
# Usage: sudo bash scripts/install-systemd.sh [--uninstall]
#
# What this does:
#   1. Install the Python package site-wide (/usr/bin/python3 -m pip install -e .)
#   2. Create runtime dirs (/var/lib/ipracticom-sweeper/{audit,snapshots})
#   3. Copy unit files to /etc/systemd/system/
#   4. Enable + start the timer
#   5. Verify with systemctl status
#
# Uninstall (--uninstall): stop + disable timer, remove unit files.
#
# Requires: systemd, root.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SYSTEMD_DIR="$PROJECT_ROOT/systemd"

# --- Helpers -----------------------------------------------------------------

log() { echo "[install-systemd] $*" >&2; }
fail() { log "ERROR: $*"; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "must run as root"

# --- Uninstall ---------------------------------------------------------------

if [ "${1:-}" = "--uninstall" ]; then
    log "Uninstalling ipracticom-sweeper timer + service..."
    systemctl stop ipracticom-sweeper.timer 2>/dev/null || true
    systemctl disable ipracticom-sweeper.timer 2>/dev/null || true
    rm -f /etc/systemd/system/ipracticom-sweeper.service
    rm -f /etc/systemd/system/ipracticom-sweeper.timer
    systemctl daemon-reload
    log "Uninstalled. Runtime dirs in /var/lib/ipracticom-sweeper kept for forensics."
    exit 0
fi

# --- Install -----------------------------------------------------------------

log "Step 1/5: Installing Python package site-wide..."
/usr/bin/python3 -m pip install -e "$PROJECT_ROOT" --break-system-packages --quiet

log "Step 2/5: Creating runtime directories..."
mkdir -p /var/lib/ipracticom-sweeper/{audit,snapshots}
chmod 750 /var/lib/ipracticom-sweeper

log "Step 3/5: Installing systemd unit files..."
cp -v "$SYSTEMD_DIR/ipracticom-sweeper.service" /etc/systemd/system/
cp -v "$SYSTEMD_DIR/ipracticom-sweeper.timer" /etc/systemd/system/
chmod 644 /etc/systemd/system/ipracticom-sweeper.{service,timer}
systemctl daemon-reload

log "Step 4/5: Enabling + starting timer..."
systemctl enable ipracticom-sweeper.timer
systemctl start ipracticom-sweeper.timer

log "Step 5/5: Verifying..."
sleep 1
if systemctl is-active --quiet ipracticom-sweeper.timer; then
    log "✓ Timer is active"
else
    fail "Timer failed to start — check 'systemctl status ipracticom-sweeper.timer'"
fi

# Run once now so the user sees immediate output
log "Triggering initial run..."
systemctl start ipracticom-sweeper.service || log "(initial run exited non-zero — check journal)"

log ""
log "=== Installation complete ==="
log ""
log "Useful commands:"
log "  systemctl status ipracticom-sweeper.timer    # timer state"
log "  systemctl status ipracticom-sweeper.service  # last run"
log "  journalctl -u ipracticom-sweeper -f          # follow logs"
log "  systemctl list-timers ipracticom-sweeper     # next 5 runs"
log "  sudo bash $0 --uninstall                     # remove"