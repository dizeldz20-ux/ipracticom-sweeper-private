#!/usr/bin/env bash
# iPracticom Sweeper — One-shot production installer.
# Run as root (or with sudo) on a fresh Ubuntu 22.04+ / Debian 12+ / RHEL 9+ host.
#
# Idempotent: safe to re-run.
#
# Usage:
#   sudo bash bootstrap.sh
#   sudo bash bootstrap.sh --uninstall

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="ipracticom-sweeper"
STATE_DIR="/var/lib/${SERVICE_NAME}"
LOG_DIR="/var/log/${SERVICE_NAME}"

# --- Colors ---
if [[ -t 1 ]]; then
    C_BLUE='\033[0;34m' C_GREEN='\033[0;32m' C_YELLOW='\033[1;33m' C_RED='\033[0;31m' C_RESET='\033[0m'
else
    C_BLUE='' C_GREEN='' C_YELLOW='' C_RED='' C_RESET=''
fi

log()  { printf "${C_BLUE}[bootstrap]${C_RESET} %s\n" "$*"; }
ok()   { printf "${C_GREEN}[bootstrap]${C_RESET} ✅ %s\n" "$*"; }
warn() { printf "${C_YELLOW}[bootstrap]${C_RESET} ⚠️  %s\n" "$*" >&2; }
err()  { printf "${C_RED}[bootstrap]${C_RESET} ❌ %s\n" "$*" >&2; }

# --- Uninstall mode ---
if [[ "${1:-}" == "--uninstall" ]]; then
    log "Uninstalling ${SERVICE_NAME}..."
    if command -v systemctl >/dev/null 2>&1; then
        systemctl disable --now "${SERVICE_NAME}.timer" 2>/dev/null || true
        rm -f "/etc/systemd/system/${SERVICE_NAME}.service" "/etc/systemd/system/${SERVICE_NAME}.timer"
        systemctl daemon-reload
        ok "systemd units removed"
    fi
    warn "State preserved at ${STATE_DIR} (delete manually if desired)"
    exit 0
fi

# --- Preflight ---
require_root() {
    if [[ $EUID -ne 0 ]]; then
        err "Must run as root. Try: sudo bash $0"
        exit 1
    fi
}

require_root

# --- Create state directories ---
mkdir -p "${STATE_DIR}" "${LOG_DIR}"
chmod 750 "${STATE_DIR}" "${LOG_DIR}"
ok "State dirs ready: ${STATE_DIR}, ${LOG_DIR}"

# --- Install package (editable from local repo) ---
log "Installing package in editable mode..."
if ! python3 -m pip install -e "${REPO_DIR}" 2>&1 | tail -3; then
    err "pip install failed"
    exit 1
fi
ok "Package installed"

# --- Create default .env if missing ---
if [[ ! -f "${REPO_DIR}/.env" ]]; then
    cp "${REPO_DIR}/.env.example" "${REPO_DIR}/.env"
    chmod 600 "${REPO_DIR}/.env"
    warn "Created ${REPO_DIR}/.env — edit it to set SLACK_WEBHOOK_URL or TELEGRAM_BOT_TOKEN"
else
    log ".env already exists, leaving untouched"
fi

# --- Install systemd units (if available) ---
if command -v systemctl >/dev/null 2>&1; then
    if [[ -f "${REPO_DIR}/scripts/install-systemd.sh" ]]; then
        log "Installing systemd units..."
        bash "${REPO_DIR}/scripts/install-systemd.sh"
        ok "systemd timer enabled"
    else
        warn "scripts/install-systemd.sh not found, skipping systemd setup"
    fi
else
    warn "systemd not available — use 'make run' or 'make quickstart' instead"
fi

# --- Verify ---
log "Verifying installation..."
if python3 -c "import ipracticom_sweeper; print('OK', ipracticom_sweeper.__file__)" 2>/dev/null; then
    ok "Package importable"
else
    err "Package not importable — check pip install output above"
    exit 1
fi

cat <<EOF

${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}
  🎉 iPracticom Sweeper installed
${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}

  📍 Install dir:    ${REPO_DIR}
  📦 State:          ${STATE_DIR}
  📝 Logs:           ${LOG_DIR}
  ⚙️  Config:        ${REPO_DIR}/.env

  👉 Next steps:
     1. Edit ${REPO_DIR}/.env (set SLACK_WEBHOOK_URL or TELEGRAM_BOT_TOKEN)
     2. Restart:  sudo systemctl restart ${SERVICE_NAME}.timer
     3. Logs:     journalctl -u ${SERVICE_NAME}.service -f
     4. Trigger:  sudo systemctl start ${SERVICE_NAME}.service
     5. UI:       make dashboard
${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}
EOF
