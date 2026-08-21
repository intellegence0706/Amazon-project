#!/usr/bin/env bash
# Start everything. One process, one URL.
set -e
cd "$(dirname "$0")"
exec python3 -m arbitrage.cli ui "$@"
