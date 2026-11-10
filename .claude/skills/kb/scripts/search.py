"""Search the support knowledge base.

    python search.py "screen went black after the update"            # JSON, for Claude
    python search.py "screen went black after the update" --pretty   # styled, for humans
    python search.py "..." --k 5

The index is opened read-only: searching can never modify the knowledge base.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb  # noqa: E402

MIN_SCORE = 0.25   # below this, report "no confident match" instead of guessing


def as_json(query: str, hits: list[kb.Hit]) -> str:
    results = []
    for h in hits:
        steps, escalate = kb.parse_body(h.body)
        results.append({"article_id": h.article_id, "title": h.title, "product": h.product,
                        "category": h.category, "error_code": h.error_code or None,
                        "score": round(h.score, 3), "matched_on": h.matched,
                        "steps": steps, "escalate_if": escalate})
    confident = bool(hits) and hits[0].score >= MIN_SCORE
    return json.dumps({"query": query, "confident_match": confident,
                       "min_score": MIN_SCORE, "results": results}, indent=2, ensure_ascii=False)


def as_pretty(query: str, hits: list[kb.Hit]) -> str:
    from pretty import bar, blue, bold, box, cyan, dim, green, grey, magenta, red, WIDTH, wrap, yellow

    out = [box("KB search", [cyan("❯ ") + query], color=blue), ""]
    for i, h in enumerate(hits, 1):
        tag = grey(f"{h.product} · {h.category}" + (f" · {h.error_code}" if h.error_code else ""))
        how = magenta("exact code") if h.matched == "error code" else grey(h.matched)
        out.append(f"  {bold(str(i))}  {bar(h.score)} {h.score:0.2f}  {bold(h.title)}")
        out.append(f"                       {tag}  {dim('matched:')} {how}")
    out.append("")

    if not hits or hits[0].score < MIN_SCORE:
        out.append(box("No confident match", [yellow("Nothing in the knowledge base clearly fits."),
                                              "Escalate rather than guess."], color=yellow))
        return "\n".join(out)

    top = hits[0]
    steps, escalate = kb.parse_body(top.body)
    lines = [grey(f"Article #{top.article_id}"), ""]
    for n, s in enumerate(steps, 1):
        lines += [green(f"{n}.") + line[2:] if j == 0 else line
                  for j, line in enumerate(wrap(s, WIDTH - 8, indent=f"{n}. "))]
    lines += ["", red("▲ Escalate if")]
    lines += wrap(escalate, WIDTH - 6, indent="  ")
    out.append(box(top.title, lines, color=green))
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("query")
    p.add_argument("--k", type=int, default=3, help="number of results (default 3)")
    p.add_argument("--pretty", action="store_true", help="styled terminal output")
    p.add_argument("--index", type=Path, default=None, help="index file (default: nearest kb_index.db)")
    a = p.parse_args()

    conn = kb.connect(a.index or kb.default_index_path(), readonly=True)
    hits = kb.search(conn, a.query, k=max(1, min(a.k, 10)))
    conn.close()
    print(as_pretty(a.query, hits) if a.pretty else as_json(a.query, hits))


if __name__ == "__main__":
    main()
