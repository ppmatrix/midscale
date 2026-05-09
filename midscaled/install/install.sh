#!/usr/bin/env bash
set -euo pipefail

# Midscale daemon installer
# Installs midscaled binary, systemd service, and configuration

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

BINARY_DEST="/usr/local/bin/midscaled"
CONFIG_DIR="/etc/midscaled"
STATE_DIR="/var/lib/midscaled"
LOG_DIR="/var/log/midscaled"
SERVICE_DEST="/etc/systemd/system/midscaled.service"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root"
    exit 1
fi

info "Installing midscaled daemon..."

if ! command -v python3 &>/dev/null; then
    error "Python 3 is required but not found"
    exit 1
fi

if ! command -v wg &>/dev/null; then
    warn "wg (WireGuard) binary not found. Install wireguard-tools."
fi

if ! command -v pip3 &>/dev/null; then
    error "pip3 is required but not found"
    exit 1
fi

info "Installing Python dependencies..."
pip3 install --prefix=/usr/local \
    "$PROJECT_DIR" 2>/dev/null || \
pip3 install --prefix=/usr/local \
    httpx structlog 2>/dev/null || true

info "Creating directories..."
mkdir -p "$CONFIG_DIR" "$STATE_DIR" "$LOG_DIR"

if [[ -f "$PROJECT_DIR/install/midscaled.env" ]]; then
    if [[ ! -f "$CONFIG_DIR/midscaled.env" ]]; then
        cp "$PROJECT_DIR/install/midscaled.env" "$CONFIG_DIR/midscaled.env"
        info "Created config file: $CONFIG_DIR/midscaled.env"
        info "  -> Edit this file with your Midscale server URL and pre-auth key"
    else
        warn "Config file already exists at $CONFIG_DIR/midscaled.env"
    fi
fi

info "Installing systemd service..."
cp "$PROJECT_DIR/install/midscaled.service" "$SERVICE_DEST"
systemctl daemon-reload

info "Enabling and starting midscaled..."
systemctl enable midscaled.service
systemctl start midscaled.service || {
    warn "Service failed to start. Check: journalctl -u midscaled.service -n 50"
}

info ""
info "Installation complete!"
info "  Service:  midscaled.service"
info "  Config:   $CONFIG_DIR/midscaled.env"
info "  State:    $STATE_DIR"
info "  Logs:     $LOG_DIR"
info ""
info "Quick commands:"
info "  sudo systemctl status midscaled"
info "  sudo journalctl -u midscaled -f"
info "  sudo systemctl restart midscaled"
