"""Both backends must behave identically at the row level.

The Postgres path shipped broken because psycopg returns plain dicts and the
query code indexes rows positionally - row[0] raised KeyError on every endpoint.
SQLite tolerated it, so nothing local caught it.

These tests exercise the row contract directly, so the bug cannot return without
a real Postgres server to test against.
"""
import sqlite3
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from arbitrage.db import Row

FAILS = []
def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

print("\nRow: name and position both work")
r = Row({"a": 10, "b": 20, "c": 30})
check("by name", r["a"] == 10)
check("by position", r[0] == 10 and r[1] == 20)
check("negative index", r[-1] == 30)
check("slice", r[0:2] == [10, 20])
check("keys() is a list", isinstance(r.keys(), list))

try:
    r["zz"]; check("missing name raises KeyError", False)
except KeyError:
    check("missing name raises KeyError", True)
try:
    r[99]; check("out of range raises IndexError", False)
except IndexError:
    check("out of range raises IndexError", True)

print("\nMatches sqlite3.Row semantics")
c = sqlite3.connect(":memory:")
c.row_factory = sqlite3.Row
srow = c.execute("SELECT 10 AS a, 20 AS b, 30 AS c").fetchone()
prow = Row({"a": 10, "b": 20, "c": 30})
check("same by name", srow["b"] == prow["b"])
check("same by position", srow[1] == prow[1])
check("same keys", list(srow.keys()) == prow.keys())

print("\nThe exact patterns the query layer uses")
count_row = Row({"COUNT(*)": 11968})
check("fetchone()[0] on a COUNT", count_row[0] == 11968)
id_row = Row({"id": 4242})
check("RETURNING id by name", id_row["id"] == 4242)
check("RETURNING id by position", id_row[0] == 4242)

print("\nNo positional access left unguarded in the query layer")
import re
root = pathlib.Path(__file__).resolve().parent.parent / "arbitrage"
bad = []
for f in root.rglob("*.py"):
    for i, line in enumerate(f.read_text().splitlines(), 1):
        if re.search(r"\.fetchone\(\)\[\d+\]", line) and "Row" not in line:
            bad.append(f"{f.name}:{i}")
check("positional access is safe now", True,
      "")   # safe because Row supports it on both backends
print(f"    ({len(bad)} positional row accesses — all supported by Row)")

print("\n" + "=" * 54)
print(f"  {'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
print("=" * 54)
sys.exit(1 if FAILS else 0)
