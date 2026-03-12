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

# ── Preflight checks ───────────────────────────────────────────────────────────
check_deps() {
  command -v docker  >/dev/null 2>&1 || die "Docker is not installed. https://docs.docker.com/get-docker/"
  docker compose version >/dev/null 2>&1 || \
    docker-compose version >/dev/null 2>&1 || \
    die "Docker Compose is not installed."
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
  $COMPOSE build --parallel
  success "All images built successfully."
  echo ""
  echo -e "  ${BOLD}Images:${RESET}"
  docker images | grep "trading-agents" || true
}

cmd_up() {
  info "Starting WhatsApp webhook server..."
  $COMPOSE up -d whatsapp-webhook
  sleep 2
  $COMPOSE ps whatsapp-webhook
  echo ""
  success "Webhook server is running."
  echo ""
  echo -e "  ${BOLD}Next steps:${RESET}"
  echo "  1. Run:  ngrok http 5001"
  echo "  2. Copy the HTTPS URL"
  echo "  3. Twilio Console → Messaging → Sandbox settings"
  echo "     → 'When a message comes in' → paste URL + /webhook"
  echo "  4. Send a stock name via WhatsApp to trigger analysis"
}

cmd_down() {
  info "Stopping all services..."
  $COMPOSE down
  success "All services stopped."
}

cmd_restart() {
  info "Restarting webhook server..."
  $COMPOSE restart whatsapp-webhook
  success "Restarted."
}

cmd_logs() {
  local follow_flag=""
  for arg in "$@"; do
    [ "$arg" = "--follow" ] || [ "$arg" = "-f" ] && follow_flag="--follow"
  done
  $COMPOSE logs $follow_flag whatsapp-webhook
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
  echo "  up                 Start the WhatsApp webhook server (background)"
  echo "  down               Stop all services"
  echo "  restart            Restart the webhook server"
  echo "  logs [-f]          Show webhook logs  (-f to follow)"
  echo "  status             Show container and image status"
  echo ""
  echo -e "${BOLD}Agent commands (run once, exit when done):${RESET}"
  echo "  fo      [args]     F&O Intraday Signal Agent"
  echo "  fund    [args]     Fundamental Analysis Agent"
  echo "  tv      [args]     TradingView Technical Analysis Agent"
  echo ""
  echo -e "${BOLD}Quick start:${RESET}"
  echo "  1.  cp .env.example .env && vim .env   # add API keys"
  echo "  2.  ./deploy.sh build"
  echo "  3.  ./deploy.sh up                     # starts WhatsApp webhook"
  echo "  4.  ./deploy.sh tv NIFTY               # run TradingView analysis"
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
    down|stop)            cmd_down  "$@" ;;
    restart)              cmd_restart "$@" ;;
    logs)                 cmd_logs  "$@" ;;
    status|ps)            cmd_status "$@" ;;
    fo|fo-signal|fno)     cmd_fo    "$@" ;;
    fund|fundamental|fa)  cmd_fund  "$@" ;;
    tv|tradingview|ta)    cmd_tv    "$@" ;;
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
