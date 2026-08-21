#!/usr/bin/env bash
# Start both processes. One command for the whole system.
set -e
cd "$(dirname "$0")"

cleanup() { kill 0 2>/dev/null; }
trap cleanup EXIT INT TERM

echo "starting engine on http://127.0.0.1:8000 ..."
python3 -m uvicorn arbitrage.web.api:app --host 127.0.0.1 --port 8000 --log-level warning &

sleep 2
echo "starting interface on http://localhost:3000 ..."
cd web && npm run start &

sleep 3
echo
echo "  ─────────────────────────────────────────────"
echo "   Open your browser at:  http://localhost:3000"
echo "  ─────────────────────────────────────────────"
echo
wait
