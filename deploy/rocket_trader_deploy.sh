#!/usr/bin/env bash
# Rocket Trader — Paper Observer deployment helper (observe-only, Paper only).
#
# Usage (run from the repository root on the host):
#   deploy/rocket_trader_deploy.sh install        # Ubuntu 22.04/24.04: Docker Engine + Compose plugin
#   deploy/rocket_trader_deploy.sh init-env       # create .env (asks for Paper keys; chmod 600)
#   deploy/rocket_trader_deploy.sh genesis        # one-time accounting genesis on an EMPTY volume
#   deploy/rocket_trader_deploy.sh up             # build and start the six observer services
#   deploy/rocket_trader_deploy.sh status         # container health summary (no secrets printed)
#   deploy/rocket_trader_deploy.sh backup         # online SQLite backup to ./backups/<UTC timestamp>/
#   deploy/rocket_trader_deploy.sh restore-test   # restore latest backup into a temp volume and verify
#
# Safety: never runs `docker compose down -v`; never edits existing databases;
# genesis refuses if any accounting database already exists. LIVE stays disabled.
set -euo pipefail

COMPOSE_FILE="docker-compose.paper-observer.yml"
PROJECT="${ROCKET_TRADER_COMPOSE_PROJECT:-rocket_trader}"
SERVICE="rocket-trader-paper-observer"
BACKUP_ROOT="${ROCKET_TRADER_BACKUP_DIR:-$(pwd)/backups}"
CONTAINER_UID=10001

die() { echo "ERROR: $*" >&2; exit 1; }
compose() { docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"; }

require_repo_root() {
  [[ -f "$COMPOSE_FILE" && -f Dockerfile.paper-observer ]] || die "Run from the Rocket_Trader repository root."
}

env_value() { # print value of KEY from .env (empty if absent)
  [[ -f .env ]] || return 0
  grep -E "^$1=" .env | tail -n1 | cut -d= -f2- || true
}

set_env_value() { # set KEY=VALUE in .env without printing it
  local key="$1" value="$2"
  touch .env && chmod 600 .env
  if grep -qE "^${key}=" .env; then
    local tmp; tmp="$(mktemp)"
    grep -vE "^${key}=" .env > "$tmp" || true
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
    cat "$tmp" > .env && rm -f "$tmp"
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

cmd_install() {
  [[ -r /etc/os-release ]] && . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || die "install supports Ubuntu only; install Docker Engine + Compose plugin manually."
  if docker compose version >/dev/null 2>&1; then echo "Docker Compose already installed."; return; fi
  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl git sqlite3
  # Docker's official apt repository (Engine + Compose plugin).
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker "$USER" || true
  echo "Docker installed. Log out and back in (or run 'newgrp docker') before continuing."
}

cmd_init_env() {
  require_repo_root
  if [[ -n "$(env_value ALPACA_API_KEY)" ]]; then echo ".env already has ALPACA_API_KEY; not changing it."; else
    local key secret
    read -r -p "Alpaca PAPER API key ID: " key
    read -r -s -p "Alpaca PAPER secret key (hidden): " secret; echo
    [[ -n "$key" && -n "$secret" ]] || die "Both keys are required."
    set_env_value ALPACA_API_KEY "$key"
    set_env_value ALPACA_SECRET_KEY "$secret"
  fi
  [[ -n "$(env_value ROCKET_TRADER_ALPACA_NEWS_SYMBOLS)" ]] || set_env_value ROCKET_TRADER_ALPACA_NEWS_SYMBOLS "SPY,QQQ,IWM,BTCUSD,ETHUSD,SOLUSD"
  chmod 600 .env
  echo ".env ready (permissions 600). It is never committed (.gitignore)."
}

cmd_genesis() {
  require_repo_root
  [[ -n "$(env_value ALPACA_API_KEY)" ]] || die "Run init-env first."
  [[ -z "$(env_value ACTIVITY_SSE_BOOTSTRAP_SINCE)" ]] || die "ACTIVITY_SSE_BOOTSTRAP_SINCE is already set: genesis was done before. Restore backups instead."
  compose build "$SERVICE"
  # Compose interpolation requires ACTIVITY_SSE_BOOTSTRAP_SINCE for every command,
  # but its real value is produced by genesis. A placeholder is used only for this run.
  local out
  out="$(ACTIVITY_SSE_BOOTSTRAP_SINCE=genesis-pending compose run --rm --no-deps -T "$SERVICE" \
        python /app/rocket_trader_paper_genesis_admin.py --data-dir /app/data --genesis-confirmed)"
  echo "$out"
  local since
  since="$(printf '%s\n' "$out" | python3 -c 'import json,sys
text=sys.stdin.read(); start=text.index("{"); end=text.rindex("}")+1
print(json.loads(text[start:end])["activity_sse_bootstrap_since"])')"
  [[ "$since" =~ ^20[0-9]{2}-[0-9]{2}-[0-9]{2}T ]] || die "Could not read genesis timestamp."
  set_env_value ACTIVITY_SSE_BOOTSTRAP_SINCE "$since"
  echo "Genesis complete. ACTIVITY_SSE_BOOTSTRAP_SINCE=$since written to .env."
}

cmd_up() {
  require_repo_root
  [[ -n "$(env_value ACTIVITY_SSE_BOOTSTRAP_SINCE)" ]] || die "Run genesis first."
  compose config >/dev/null
  compose up -d --build
  compose ps
}

cmd_status() {
  require_repo_root
  compose ps --format '{{.Service}}\t{{.State}}\t{{.Health}}'
}

cmd_backup() {
  require_repo_root
  local stamp dest
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dest="$BACKUP_ROOT/$stamp"
  mkdir -p "$dest"
  sudo chown "$CONTAINER_UID:$CONTAINER_UID" "$dest" 2>/dev/null || chmod 777 "$dest"
  ACTIVITY_SSE_BOOTSTRAP_SINCE="${ACTIVITY_SSE_BOOTSTRAP_SINCE:-$(env_value ACTIVITY_SSE_BOOTSTRAP_SINCE)}" \
    compose run --rm --no-deps -T -v "$dest:/backup" -v "$(pwd)/deploy:/deploy:ro" "$SERVICE" \
    python /deploy/sqlite_backup.py backup --source /app/data --dest /backup
  [[ -f .env ]] && cp .env "$dest/env.backup" && chmod 600 "$dest/env.backup" 2>/dev/null || true
  echo "Backup written to $dest (contains .env copy: keep it private and off-host)."
}

cmd_restore_test() {
  require_repo_root
  local latest
  latest="$(ls -1d "$BACKUP_ROOT"/*/ 2>/dev/null | sort | tail -n1)"
  [[ -n "$latest" ]] || die "No backup found in $BACKUP_ROOT."
  # Restores into a scratch directory inside a throw-away container; the live
  # volume is never written.
  ACTIVITY_SSE_BOOTSTRAP_SINCE="${ACTIVITY_SSE_BOOTSTRAP_SINCE:-$(env_value ACTIVITY_SSE_BOOTSTRAP_SINCE)}" \
    compose run --rm --no-deps -T -v "$latest:/backup:ro" -v "$(pwd)/deploy:/deploy:ro" "$SERVICE" \
    python /deploy/sqlite_backup.py restore-test --backup /backup --target /tmp/restore_test \
    || die "Restore test FAILED for $latest"
  echo "Restore test passed for $latest (live volume untouched)."
}

main() {
  case "${1:-}" in
    install) cmd_install ;;
    init-env) cmd_init_env ;;
    genesis) cmd_genesis ;;
    up) cmd_up ;;
    status) cmd_status ;;
    backup) cmd_backup ;;
    restore-test) cmd_restore_test ;;
    *) sed -n '2,13p' "$0"; exit 2 ;;
  esac
}

main "$@"
