#!/usr/bin/env bash
# Every check, in one command.
#
#   ./run-tests.sh                                  test against local SQLite
#   DATABASE_URL='postgres://…' ./run-tests.sh      test against Supabase
set -e
cd "$(dirname "$0")"

python3 tests/test_matching.py
python3 tests/test_backends.py
python3 tests/test_sql_portability.py
python3 tests/smoke.py
python3 -m arbitrage.cli verify --offline
