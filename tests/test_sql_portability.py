"""Static check for SQL that works on SQLite but breaks on Postgres.

Two of these shipped and failed in production - ROUND(float, n) and an
unguarded division. SQLite is permissive where Postgres is strict, so local
testing cannot catch them and no Postgres server is available here.

SQL literals are pulled out of the AST rather than matched line by line, so
Python's own round() and strftime() are never mistaken for SQL.
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "arbitrage"
SQL_KEYWORDS = re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|"
                          r"CREATE\s+TABLE)\b", re.I)

RULES = [
    ("ROUND with precision on a float",
     re.compile(r"ROUND\s*\((?![^;]{0,200}?CAST)[^;]*?,\s*\d+\s*\)", re.I),
     "Postgres has no ROUND(double precision, integer), only ROUND(numeric, integer).",
     "ROUND(CAST(expr AS NUMERIC), 1)"),

    ("division without a zero guard",
     re.compile(r"/\s*(?!NULLIF)[a-z_]+\.[a-z_]+\s*[*)]", re.I),
     "SQLite returns NULL on divide-by-zero; Postgres raises an error.",
     "/ NULLIF(col, 0)"),

    ("SQLite-only function",
     re.compile(r"\b(IFNULL|GROUP_CONCAT)\s*\(|\bstrftime\s*\(|\btypeof\s*\(", re.I),
     "Not available in Postgres.",
     "COALESCE / STRING_AGG / standard SQL"),

    ("INSERT OR REPLACE / IGNORE",
     re.compile(r"INSERT\s+OR\s+(REPLACE|IGNORE)", re.I),
     "SQLite-only syntax.",
     "INSERT ... ON CONFLICT ... DO UPDATE / DO NOTHING"),

    ("AUTOINCREMENT",
     re.compile(r"\bAUTOINCREMENT\b", re.I),
     "SQLite-only.",
     "Use the schema templating in db.py"),
]


def sql_literals(path):
    """Yield (line, text) for every string constant that looks like SQL."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if SQL_KEYWORDS.search(node.value):
                yield node.lineno, node.value


problems = []
scanned = 0
for path in sorted(ROOT.rglob("*.py")):
    if path.name == "db.py":            # owns backend-specific schema on purpose
        continue
    scanned += 1
    for lineno, sql in sql_literals(path):
        for name, pat, why, fix in RULES:
            m = pat.search(sql)
            if m:
                problems.append((path.name, lineno, name, m.group(0)[:58], why, fix))

print("\nSQL PORTABILITY CHECK")
print("─" * 64)
if problems:
    for f, i, name, snippet, why, fix in problems:
        print(f"  ✗ {f}:{i}  {name}")
        print(f"      {snippet}")
        print(f"      {why}")
        print(f"      → {fix}\n")
    print("─" * 64)
    print(f"  {len(problems)} problem(s) — these fail on Postgres.\n")
    sys.exit(1)

print(f"  ✓ SQL literals in {scanned} modules are portable")
print("─" * 64)
print("  ALL PASSED\n")
