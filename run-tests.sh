#!/usr/bin/env bash
# Every check, in one command.
set -e
cd "$(dirname "$0")"
python3 tests/test_matching.py
python3 tests/test_backends.py
python3 tests/test_sql_portability.py
python3 -m arbitrage.cli verify --offline
