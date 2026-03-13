#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# deploy.sh — Claude Trading Agents management script
# ──────────────────────────────────────────────────────────────────────────────
#
# Usage:
#   ./deploy.sh build                    Build all Docker images
#   ./deploy.sh up                       Start the WhatsApp webhook server
#   ./deploy.sh down                     Stop all running services
#   ./deploy.sh restart                  Restart the webhook server
#   ./deploy.sh logs [--follow]          Show webhook server logs
#   ./deploy.sh status                   Show container status
#
#   ./deploy.sh fo      [args...]        Run F&O Signal Agent
#   ./deploy.sh fund    [args...]        Run Fundamental Analysis Agent
#   ./deploy.sh tv      [args...]        Run TradingView Technical Analysis Agent
#
# Examples:
#   ./deploy.sh fo --capital 500000 --instrument NIFTY
#   ./deploy.sh fund RELIANCE
#   ./deploy.sh fund INFY TCS --notify
#   ./deploy.sh tv NIFTY --timeframe 15m
#   ./deploy.sh tv HDFCBANK --timeframe 4h --provider gemini
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Ensure Homebrew and its binaries are on PATH (macOS) ──────────────────────
for _brew_prefix in /opt/homebrew /usr/local; do
  [ -d "$_brew_prefix/bin" ] && export PATH="$_brew_prefix/bin:$PATH"
done
unset _brew_prefix

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}${BOLD}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}${BOLD}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}${BOLD}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}${BOLD}[ERROR]${RESET} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Banner ─────────────────────────────────────────────────────────────────────
banner() {
  echo -e "${CYAN}${BOLD}"
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║          Claude Trading Agents — Deploy Script               ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo -e "${RESET}"
}

# ── Docker installation ────────────────────────────────────────────────────────
install_docker() {
  info "Docker not found. Attempting automatic installation..."

  OS="$(uname -s)"
  ARCH="$(uname -m)"

  case "$OS" in
    Linux)
      # Detect distro
      if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO="${ID:-unknown}"
      else
        DISTRO="unknown"
      fi

      info "Detected Linux distro: $DISTRO"

      case "$DISTRO" in
        ubuntu|debian|linuxmint|pop)
          info "Installing Docker via apt (Ubuntu/Debian)..."
          sudo apt-get update -qq
          sudo apt-get install -y ca-certificates curl gnupg lsb-release
          sudo install -m 0755 -d /etc/apt/keyrings
          curl -fsSL https://download.docker.com/linux/${DISTRO}/gpg \
            | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
          sudo chmod a+r /etc/apt/keyrings/docker.gpg
          echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
            https://download.docker.com/linux/${DISTRO} $(lsb_release -cs) stable" \
            | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
          sudo apt-get update -qq
          sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
          sudo usermod -aG docker "$USER" || true
          ;;
        centos|rhel|rocky|almalinux)
          info "Installing Docker via dnf (RHEL/CentOS)..."
          sudo dnf -y install dnf-plugins-core
          sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
          sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
          sudo systemctl enable --now docker
          sudo usermod -aG docker "$USER" || true
          ;;
        fedora)
          info "Installing Docker via dnf (Fedora)..."
          sudo dnf -y install dnf-plugins-core
          sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
          sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
          sudo systemctl enable --now docker
          sudo usermod -aG docker "$USER" || true
          ;;
        amzn)
          info "Installing Docker (Amazon Linux)..."
          sudo yum update -y
          sudo yum install -y docker
          sudo systemctl enable --now docker
          sudo usermod -aG docker "$USER" || true
          # Install Compose V2 plugin manually on Amazon Linux
          COMPOSE_VER="v2.27.0"
          sudo mkdir -p /usr/local/lib/docker/cli-plugins
          sudo curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VER}/docker-compose-linux-$(uname -m)" \
            -o /usr/local/lib/docker/cli-plugins/docker-compose
          sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
          ;;
        *)
          info "Unknown distro '$DISTRO'. Using Docker convenience install script..."
          curl -fsSL https://get.docker.com | sudo sh
          sudo usermod -aG docker "$USER" || true
          ;;
      esac
      ;;

    Darwin)
      # macOS — check for Homebrew first, then guide user to Docker Desktop
      if command -v brew >/dev/null 2>&1; then
        info "Installing Docker Desktop via Homebrew..."
        brew install --cask docker
        info "Launching Docker Desktop..."
        open -a Docker || true
        info "Waiting for Docker daemon to start (up to 60s)..."
        for i in $(seq 1 12); do
          docker info >/dev/null 2>&1 && break || sleep 5
        done
      else
        warn "Homebrew not found."
        echo ""
        echo "  Please install Docker Desktop for macOS manually:"
        echo "  → https://docs.docker.com/desktop/install/mac-install/"
        echo ""
        echo "  Or install Homebrew first:"
        echo "  → /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        die "Cannot auto-install Docker on macOS without Homebrew."
      fi
      ;;

    *)
      warn "Unsupported OS: $OS"
      echo ""
      echo "  Please install Docker manually: https://docs.docker.com/get-docker/"
      die "Cannot auto-install Docker on $OS."
      ;;
  esac

  # Final verification
  if command -v docker >/dev/null 2>&1; then
    success "Docker installed: $(docker --version)"
  else
    die "Docker installation failed. Please install manually: https://docs.docker.com/get-docker/"
  fi
}

install_mcp_server() {
  # MCP server is already baked into the Docker image via the Dockerfile.
  # This installs it on the HOST for local (non-Docker) runs only.
  info "Checking TradingView MCP server on host..."

  # Resolve pip: try pip3, pip, then python3 -m pip
  PIP=""
  for _pip in pip3 pip; do
    command -v "$_pip" >/dev/null 2>&1 && PIP="$_pip" && break
  done
  if [ -z "$PIP" ] && command -v python3 >/dev/null 2>&1; then
    python3 -m pip --version >/dev/null 2>&1 && PIP="python3 -m pip"
  fi

  if [ -z "$PIP" ]; then
    info "pip not found on host — MCP server will run inside Docker only (this is fine)."
    return 0
  fi

  info "Installing mcp + mcp-tradingview-server on host via $PIP..."
  $PIP install --quiet mcp 2>&1 | tail -2

  # Try PyPI first, then GitHub source
  if $PIP install --quiet mcp-tradingview-server 2>/dev/null; then
    success "mcp-tradingview-server installed from PyPI."
  elif $PIP install --quiet "git+https://github.com/bidouilles/mcp-tradingview-server.git" 2>/dev/null; then
    success "mcp-tradingview-server installed from GitHub."
  else
    info "mcp-tradingview-server not available — tradingview_ta fallback will be used inside Docker."
  fi
}

install_compose() {
  info "Installing Docker Compose plugin..."
  COMPOSE_VER="v2.27.0"
  OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
  ARCH="$(uname -m)"
  [ "$ARCH" = "x86_64" ] && ARCH="x86_64"
  [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ] && ARCH="aarch64"

  sudo mkdir -p /usr/local/lib/docker/cli-plugins
  sudo curl -SL \
    "https://github.com/docker/compose/releases/download/${COMPOSE_VER}/docker-compose-${OS}-${ARCH}" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  success "Docker Compose installed: $(docker compose version)"
}

# ── Preflight checks ───────────────────────────────────────────────────────────
check_deps() {
  # ── Docker ──
  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker is not installed."
    read -r -p "  Install Docker automatically? [y/N] " answer
    case "$answer" in
      [yY][eE][sS]|[yY])
        install_docker
        ;;
      *)
        die "Docker is required. Install it from: https://docs.docker.com/get-docker/"
        ;;
    esac
  else
    success "Docker: $(docker --version)"
  fi

  # ── Docker Compose ──
  if docker compose version >/dev/null 2>&1; then
    success "Docker Compose: $(docker compose version)"
  elif command -v docker-compose >/dev/null 2>&1; then
    success "Docker Compose (legacy): $(docker-compose --version)"
  else
    warn "Docker Compose plugin not found."
    read -r -p "  Install Docker Compose plugin automatically? [y/N] " answer
    case "$answer" in
      [yY][eE][sS]|[yY])
        install_compose
        ;;
      *)
        die "Docker Compose is required. See: https://docs.docker.com/compose/install/"
        ;;
    esac
  fi

  # ── Docker daemon running? ──
  if ! docker info >/dev/null 2>&1; then
    warn "Docker daemon is not running."
    _wait_for_daemon() {
      local max_wait="${1:-120}"
      local interval=5
      local elapsed=0
      while [ "$elapsed" -lt "$max_wait" ]; do
        docker info >/dev/null 2>&1 && return 0
        printf "  Waiting for Docker daemon... %ds/%ds\r" "$elapsed" "$max_wait"
        sleep "$interval"
        elapsed=$(( elapsed + interval ))
      done
      echo ""
      return 1
    }

    OS="$(uname -s)"
    case "$OS" in
      Darwin)
        # Priority: 1) Colima  2) Docker Desktop
        _BREW="/opt/homebrew/bin/brew"
        _COLIMA="$(command -v colima 2>/dev/null || echo /opt/homebrew/bin/colima)"

        if command -v colima >/dev/null 2>&1 || [ -x /opt/homebrew/bin/colima ]; then
          info "Starting Docker via Colima..."
          "$_COLIMA" start 2>&1 | grep -v "^$" || true
          info "Waiting up to 60s for Docker daemon..."
          if _wait_for_daemon 60; then
            echo ""
            success "Docker daemon is ready (Colima)."
          else
            echo ""
            warn "Colima start timed out — retrying with fresh VM..."
            "$_COLIMA" stop 2>/dev/null || true
            "$_COLIMA" start --cpu 2 --memory 4 2>&1 | grep -v "^$" || true
            _wait_for_daemon 90 && echo "" && success "Docker daemon is ready." || \
              die "Colima failed to start. Run manually: colima start\nThen retry: ./deploy.sh"
          fi

        elif [ -d "/Applications/Docker.app" ]; then
          info "Starting Docker Desktop..."
          open -a Docker
          info "Waiting up to 120s for Docker daemon..."
          if _wait_for_daemon 120; then
            echo ""
            success "Docker daemon is ready (Docker Desktop)."
          else
            echo ""
            warn "Daemon still not ready — restarting Docker Desktop..."
            osascript -e 'quit app "Docker"' 2>/dev/null || killall Docker 2>/dev/null || true
            sleep 3
            open -a Docker
            info "Waiting another 90s..."
            _wait_for_daemon 90 && echo "" && success "Docker daemon is ready." || \
              die "Docker Desktop did not start in time.
  Try: open Docker Desktop manually, wait for the whale to stop animating, then re-run ./deploy.sh"
          fi

        elif [ -x "$_BREW" ]; then
          warn "No Docker runtime found. Installing Colima via Homebrew..."
          "$_BREW" install colima docker docker-compose
          # Register compose plugin
          mkdir -p ~/.docker
          python3 -c "
import json, os
p = os.path.expanduser('~/.docker/config.json')
c = {}
if os.path.exists(p):
    try: c = json.load(open(p))
    except: pass
c['cliPluginsExtraDirs'] = ['/opt/homebrew/lib/docker/cli-plugins']
json.dump(c, open(p,'w'), indent=2)
" 2>/dev/null || true
          /opt/homebrew/bin/colima start --cpu 2 --memory 4
          _wait_for_daemon 90 && echo "" && success "Docker daemon is ready." || \
            die "Colima failed after install. Try: colima start && ./deploy.sh"

        else
          die "No Docker runtime found and Homebrew is not available.
  Option 1 (recommended): Install Colima
    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
    brew install colima docker docker-compose && colima start
  Option 2: Install Docker Desktop
    https://docs.docker.com/desktop/install/mac-install/"
        fi
        ;;

      Linux)
        info "Starting Docker service..."
        # Try systemd first, then init.d, then dockerd directly
        if command -v systemctl >/dev/null 2>&1; then
          sudo systemctl start docker 2>/dev/null && info "systemctl: docker started" || true
        fi
        if ! docker info >/dev/null 2>&1; then
          sudo service docker start 2>/dev/null && info "service: docker started" || true
        fi
        if ! docker info >/dev/null 2>&1; then
          warn "Starting dockerd in background as fallback..."
          sudo dockerd > /tmp/dockerd.log 2>&1 &
        fi
        info "Waiting up to 60s for Docker daemon..."
        if _wait_for_daemon 60; then
          echo ""
          success "Docker daemon is ready."
        else
          echo ""
          die "Docker daemon did not start. Diagnostics:
  Check logs:     sudo journalctl -u docker --no-pager -n 30
  Check socket:   ls -la /var/run/docker.sock
  Manual start:   sudo systemctl start docker
  Then retry:     ./deploy.sh"
        fi
        ;;

      *)
        die "Cannot auto-start Docker on $OS. Please start Docker manually and retry."
        ;;
    esac
  else
    success "Docker daemon: running"
  fi
}

check_env() {
  if [ ! -f ".env" ]; then
    warn ".env file not found. Copying .env.example → .env"
    cp .env.example .env
    warn "Please edit .env and add your API keys before running agents."
    echo ""
  fi

  # Check at least one LLM key is present
  local has_key=false
  for var in ANTHROPIC_API_KEY OPENAI_API_KEY GOOGLE_API_KEY MISTRAL_API_KEY; do
    val=$(grep -E "^${var}=" .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    if [ -n "$val" ] && [ "$val" != "your-anthropic-api-key-here" ] && [[ "$val" != *"your-"* ]]; then
      has_key=true
      break
    fi
  done

  if [ "$has_key" = false ]; then
    warn "No LLM API key found in .env. Add at least one of:"
    warn "  ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, MISTRAL_API_KEY"
  fi
}

# Resolve compose command (Docker Compose V2 vs V1)
compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  else
    echo "docker-compose"
  fi
}

COMPOSE=$(compose_cmd)

# ── Commands ───────────────────────────────────────────────────────────────────

cmd_build() {
  info "Building all Docker images..."
  install_mcp_server
  $COMPOSE build --parallel
  success "All images built successfully."
  echo ""
  echo -e "  ${BOLD}Images:${RESET}"
  docker images | grep "trading-agents" || true
}

cmd_up() {
  info "Starting UI dashboard + WhatsApp webhook server..."
  $COMPOSE up -d ui whatsapp-webhook
  sleep 3
  $COMPOSE ps ui whatsapp-webhook
  echo ""
  success "Services are running."
  echo ""
  echo -e "  ${BOLD}Dashboard:${RESET}  http://localhost:${UI_PORT:-8501}"
  echo ""
  echo -e "  ${BOLD}WhatsApp setup:${RESET}"
  echo "  1. Run:  ngrok http 5001"
  echo "  2. Copy the HTTPS URL"
  echo "  3. Twilio Console → Messaging → Sandbox settings"
  echo "     → 'When a message comes in' → paste URL + /webhook"
  echo "  4. Send a stock name via WhatsApp to trigger analysis"
}

cmd_ui() {
  info "Starting Streamlit dashboard only..."
  $COMPOSE up -d ui
  sleep 3
  success "Dashboard running at http://localhost:${UI_PORT:-8501}"
}

cmd_down() {
  info "Stopping all services..."
  $COMPOSE down
  success "All services stopped."
}

cmd_restart() {
  info "Restarting services..."
  $COMPOSE restart ui whatsapp-webhook
  success "Restarted."
}

cmd_logs() {
  local follow_flag=""
  local svc="ui whatsapp-webhook"
  for arg in "$@"; do
    [ "$arg" = "--follow" ] || [ "$arg" = "-f" ] && follow_flag="--follow"
    [ "$arg" = "ui" ]       && svc="ui"
    [ "$arg" = "webhook" ]  && svc="whatsapp-webhook"
  done
  $COMPOSE logs $follow_flag $svc
}

cmd_status() {
  echo -e "${BOLD}Running containers:${RESET}"
  $COMPOSE ps
  echo ""
  echo -e "${BOLD}Images:${RESET}"
  docker images | grep "trading-agents" 2>/dev/null || echo "  (none built yet — run: ./deploy.sh build)"
}

# ── CLI Agent runners ──────────────────────────────────────────────────────────

cmd_fo() {
  info "F&O Signal Agent"
  if [ $# -eq 0 ]; then
    echo -e "  ${BOLD}Usage:${RESET} ./deploy.sh fo --capital <amount> --instrument <symbol>"
    echo "  ${BOLD}Examples:${RESET}"
    echo "    ./deploy.sh fo --capital 500000 --instrument NIFTY"
    echo "    ./deploy.sh fo --capital 200000 --instrument BANKNIFTY --provider gemini"
    echo ""
    $COMPOSE run --rm --profile tools fo-signal --help 2>/dev/null || \
      $COMPOSE --profile tools run --rm fo-signal --help
    return
  fi
  $COMPOSE --profile tools run --rm fo-signal "$@"
}

cmd_fund() {
  info "Fundamental Analysis Agent"
  if [ $# -eq 0 ]; then
    echo -e "  ${BOLD}Usage:${RESET} ./deploy.sh fund <SYMBOL> [SYMBOL2 ...] [--notify] [--no-notify]"
    echo "  ${BOLD}Examples:${RESET}"
    echo "    ./deploy.sh fund RELIANCE"
    echo "    ./deploy.sh fund INFY TCS --notify"
    echo "    ./deploy.sh fund BAJFINANCE --provider openai"
    echo ""
    $COMPOSE --profile tools run --rm fundamental --help
    return
  fi
  $COMPOSE --profile tools run --rm fundamental "$@"
}

cmd_tv() {
  info "TradingView Technical Analysis Agent"
  if [ $# -eq 0 ]; then
    echo -e "  ${BOLD}Usage:${RESET} ./deploy.sh tv <SYMBOL> [--timeframe TF] [--provider PROVIDER]"
    echo "  ${BOLD}Examples:${RESET}"
    echo "    ./deploy.sh tv NIFTY"
    echo "    ./deploy.sh tv RELIANCE --timeframe 15m"
    echo "    ./deploy.sh tv HDFCBANK --timeframe 4h --provider gemini"
    echo "    ./deploy.sh tv BANKNIFTY --timeframe 1D --quiet"
    echo ""
    $COMPOSE --profile tools run --rm tradingview --help
    return
  fi
  $COMPOSE --profile tools run --rm tradingview "$@"
}

# ── Help ───────────────────────────────────────────────────────────────────────

cmd_help() {
  banner
  echo -e "${BOLD}Infrastructure commands:${RESET}"
  echo "  build              Build all Docker images"
  echo "  up                 Start UI dashboard + WhatsApp webhook (background)"
  echo "  ui                 Start UI dashboard only"
  echo "  down               Stop all services"
  echo "  restart            Restart all services"
  echo "  logs [-f] [ui|webhook]   Show logs  (-f to follow)"
  echo "  status             Show container and image status"
  echo ""
  echo -e "${BOLD}Agent commands (run once, exit when done):${RESET}"
  echo "  fo      [args]     F&O Intraday Signal Agent"
  echo "  fund    [args]     Fundamental Analysis Agent"
  echo "  tv      [args]     TradingView Technical Analysis Agent"
  echo "  mcp                Install TradingView MCP server on host (for local runs)"
  echo ""
  echo -e "${BOLD}Quick start:${RESET}"
  echo "  1.  cp .env.example .env && vim .env   # add API keys"
  echo "  2.  ./deploy.sh build"
  echo "  3.  ./deploy.sh up                     # starts UI + webhook"
  echo "       → open http://localhost:8501"
  echo "  4.  ./deploy.sh tv NIFTY               # CLI: TradingView analysis"
  echo "  5.  ./deploy.sh fo --capital 500000 --instrument NIFTY"
  echo "  6.  ./deploy.sh fund RELIANCE"
}

# ── Entrypoint ─────────────────────────────────────────────────────────────────

main() {
  check_deps
  check_env

  local cmd="${1:-help}"
  shift || true

  case "$cmd" in
    build)                cmd_build "$@" ;;
    up|start)             cmd_up    "$@" ;;
    ui|dashboard)         cmd_ui    "$@" ;;
    down|stop)            cmd_down  "$@" ;;
    restart)              cmd_restart "$@" ;;
    logs)                 cmd_logs  "$@" ;;
    status|ps)            cmd_status "$@" ;;
    fo|fo-signal|fno)     cmd_fo    "$@" ;;
    fund|fundamental|fa)  cmd_fund  "$@" ;;
    tv|tradingview|ta)    cmd_tv    "$@" ;;
    mcp|install-mcp)      install_mcp_server ;;
    help|--help|-h)       cmd_help  ;;
    *)
      error "Unknown command: $cmd"
      echo ""
      cmd_help
      exit 1
      ;;
  esac
}

# Change to the script's directory so relative paths work from anywhere
cd "$(dirname "$0")"

main "$@"
