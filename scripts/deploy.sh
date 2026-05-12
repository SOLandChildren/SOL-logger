#!/usr/bin/env bash
set -euo pipefail

# Manual deploy of SOL-logger to solar.usilu.net.
#
# Prerequisites:
#   - You are connected to USI VPN (solar.usilu.net is on USI's internal network)
#   - rsync and ssh installed (default on macOS)
#   - logger/search-app/API_keys.json and service_account.json exist locally
#
# Usage:  scripts/deploy.sh

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER_USER="rotam" 
SERVER_HOST="solar.usilu.net"
REMOTE_DIR="sol-logger"   # path is relative to $HOME on the server

cd "$REPO_ROOT"

echo "==> Pre-flight checks"

for f in logger/search-app/API_keys.json logger/search-app/service_account.json; do
    if [ ! -s "$REPO_ROOT/$f" ]; then
        echo "    ERROR: missing or empty file: $f" >&2
        echo "    Place it locally (it's gitignored) before deploying." >&2
        exit 1
    fi
done
echo "    secrets present"

if ! nc -z -G 3 "$SERVER_HOST" 22 >/dev/null 2>&1; then
    echo "    ERROR: $SERVER_HOST:22 is not reachable from here." >&2
    echo "    Are you on USI VPN? Look for a utun/tun interface with a 10.x address:" >&2
    echo "      ifconfig | awk '/^utun|^tun/ {i=\$1} /inet / && i {print i, \$2; i=\"\"}'" >&2
    exit 1
fi
echo "    $SERVER_HOST:22 reachable (VPN looks fine)"

echo ""
echo "==> Rsync to $SERVER_USER@$SERVER_HOST:$REMOTE_DIR/"

rsync -az --delete-after \
    --exclude='.git/' \
    --exclude='.github/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='logger/logs/' \
    --exclude='logger/old_logs/' \
    --exclude='logger/search-engine/datasets/' \
    --exclude='logger/search-engine/index/' \
    --exclude='scripts/' \
    --exclude='DEPLOY-TODO.txt' \
    --exclude='README.md' \
    --exclude='experiments/' \
    ./ "$SERVER_USER@$SERVER_HOST:$REMOTE_DIR/"

echo ""
echo "==> Build + restart on server (Vertex-only profile)"

ssh "$SERVER_USER@$SERVER_HOST" \
    'cd "$HOME/sol-logger/logger" && mkdir -p logs && docker compose up --build -d --remove-orphans && docker compose ps'

echo ""
echo "==> Deploy complete."
echo ""
echo "Smoke-test from server:"
echo "    ssh $SERVER_USER@$SERVER_HOST 'curl -I http://127.0.0.1:7001/'"
echo ""
echo "Smoke-test from your laptop (VPN must be on):"
echo "    curl -I http://solar.usilu.net:7001/"
echo ""
echo "Tail live logs:"
echo "    ssh $SERVER_USER@$SERVER_HOST 'cd sol-logger/logger && docker compose logs -f search_app'"
