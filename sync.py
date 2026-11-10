"""Sync a knowledge-base CSV export into the local vector index.

    python sync.py exports/kb_export_2026-10-01.csv     # first load
    python sync.py exports/kb_export_2026-11-09.csv     # later export: only changes are re-embedded

Run it on a schedule (cron / Task Scheduler) against each new export or API pull, and the
index stays current without rebuilding: new articles are added, edited ones re-embedded,
deleted ones removed, and everything else is left alone.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "kb" / "scripts"))
import kb  # noqa: E402
from pretty import blue, bold, box, green, grey, red, yellow  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("export", type=Path, help="CSV export of the knowledge base")
    p.add_argument("--index", type=Path, default=ROOT / "kb_index.db")
    a = p.parse_args()

    started = time.perf_counter()
    articles = kb.read_export(a.export)
    conn = kb.connect(a.index)
    res = kb.sync(conn, articles, source=a.export.name)
    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    conn.close()
    ms = (time.perf_counter() - started) * 1000

    lines = [grey(f"source  {a.export.name}"), ""]
    lines += [green("  + ") + t for t in res.added]
    lines += [yellow("  ~ ") + t for t in res.updated]
    lines += [red("  - ") + t for t in res.removed]
    if not (res.added or res.updated or res.removed):
        lines.append(grey("  no changes"))
    lines += ["",
              f"{green(str(len(res.added)) + ' added')}  {yellow(str(len(res.updated)) + ' updated')}  "
              f"{red(str(len(res.removed)) + ' removed')}  {grey(str(res.unchanged) + ' unchanged')}",
              grey(f"index   {total} articles · {ms:.0f} ms")]
    print(box("KB sync", lines, color=blue))


if __name__ == "__main__":
    main()
