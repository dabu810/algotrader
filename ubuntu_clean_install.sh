#!/usr/bin/env bash
# ubuntu_clean_install.sh
# Uninstall Docker completely, install Docker CE fresh, then build & start trading agents.
# Run as root or with sudo: sudo bash ubuntu_clean_install.sh
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── 0. Must run as root ───────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  error "Please run as root: sudo bash $0"
  exit 1
fi

# Remember the original (non-root) user who invoked sudo
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "$USER")}"
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

info "Running as root on behalf of user: $REAL_USER"

# ── 1. Stop & remove all containers ──────────────────────────────────────────
info "Stopping all running containers (if Docker is available)…"
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
  docker ps -aq | xargs -r docker stop  2>/dev/null || true
  docker ps -aq | xargs -r docker rm -f 2>/dev/null || true
  docker system prune -af --volumes      2>/dev/null || true
  info "All containers removed."
else
  warn "Docker not running or not installed — skipping container cleanup."
fi

# ── 2. Uninstall Docker (all known package names) ────────────────────────────
info "Uninstalling Docker packages…"
apt-get remove -y --purge \
  docker \
  docker-engine \
  docker.io \
  containerd \
  runc \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin \
  docker-ce-rootless-extras \
  2>/dev/null || true

apt-get autoremove -y --purge 2>/dev/null || true

# ── 3. Remove Docker data & config directories ───────────────────────────────
info "Removing Docker data directories…"
rm -rf /var/lib/docker
rm -rf /var/lib/containerd
rm -rf /etc/docker
rm -rf /run/docker
rm -rf /run/docker.sock
rm -f  /usr/local/bin/docker-compose

# Remove user-level docker config (credential stores, etc.)
if [[ -d "$REAL_HOME/.docker" ]]; then
  info "Removing $REAL_HOME/.docker …"
  rm -rf "$REAL_HOME/.docker"
fi

# Remove old Docker apt repo files
rm -f /etc/apt/sources.list.d/docker*.list
rm -f /etc/apt/keyrings/docker.gpg
rm -f /etc/apt/keyrings/docker.asc
rm -f /usr/share/keyrings/docker-archive-keyring.gpg

info "Docker fully uninstalled."

# ── 4. Install prerequisites ─────────────────────────────────────────────────
info "Installing prerequisites…"
apt-get update -y
apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  lsb-release \
  apt-transport-https \
  software-properties-common

# ── 5. Add Docker's official GPG key & apt repo ──────────────────────────────
info "Adding Docker apt repository…"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -y

# ── 6. Install Docker CE + plugins ───────────────────────────────────────────
info "Installing Docker CE…"
apt-get install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin

# ── 7. Enable & start Docker daemon ──────────────────────────────────────────
info "Enabling Docker daemon…"
systemctl enable docker
systemctl start  docker

# Wait for daemon
MAX_WAIT=60
WAITED=0
until docker info &>/dev/null 2>&1; do
  if [[ $WAITED -ge $MAX_WAIT ]]; then
    error "Docker daemon did not start within ${MAX_WAIT}s."
    journalctl -u docker --no-pager -n 30
    exit 1
  fi
  printf "\r  Waiting for Docker daemon… %ds" "$WAITED"
  sleep 2
  WAITED=$((WAITED + 2))
done
echo ""
info "Docker daemon is up."

# ── 8. Add user to docker group ──────────────────────────────────────────────
if id "$REAL_USER" &>/dev/null; then
  usermod -aG docker "$REAL_USER"
  info "Added $REAL_USER to docker group (re-login required for group to take effect)."
fi

docker --version
docker compose version

# ── 9. Build & start trading agents ──────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f "deploy.sh" ]]; then
  warn "deploy.sh not found in $SCRIPT_DIR — skipping build step."
  info "Docker CE installed successfully. Run './deploy.sh build && ./deploy.sh up' manually."
  exit 0
fi

# Run deploy.sh as the real (non-root) user so file ownership is correct
info "Running clean build…"
sudo -u "$REAL_USER" bash deploy.sh build

info "Starting services…"
sudo -u "$REAL_USER" bash deploy.sh up

echo ""
info "================================================================"
info " All done! Services are starting."
info " Streamlit UI  →  http://localhost:8501"
info " WhatsApp hook →  http://localhost:5001"
info "================================================================"
warn "NOTE: Log out and back in (or run 'newgrp docker') so that"
warn "      '$REAL_USER' can run Docker without sudo."
