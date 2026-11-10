"""Terminal styling helpers (ANSI colours + box drawing), standard library only."""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap

if os.name == "nt":
    os.system("")                          # enable ANSI escape handling on Windows consoles
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

COLOR = sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1"
WIDTH = min(int(os.environ.get("KB_WIDTH", 0)) or shutil.get_terminal_size((88, 24)).columns, 88)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _c(code: str):
    return lambda s: f"\x1b[{code}m{s}\x1b[0m" if COLOR else s


bold, dim = _c("1"), _c("2")
cyan, green, yellow, red, magenta, blue = (_c(c) for c in ("96", "92", "93", "91", "95", "94"))
grey = _c("90")


def visible_len(s: str) -> int:
    return len(_ANSI.sub("", s))


def box(title: str, lines: list[str], color=cyan, width: int = WIDTH) -> str:
    inner = width - 4
    top = color("╭─ ") + bold(title) + " " + color("─" * max(inner - visible_len(title) - 1, 0) + "╮")
    out = [top]
    for line in lines:
        pad = inner - visible_len(line)
        out.append(color("│ ") + line + " " * max(pad, 0) + color(" │"))
    out.append(color("╰" + "─" * (width - 2) + "╯"))
    return "\n".join(out)


def wrap(text: str, width: int, indent: str = "") -> list[str]:
    return textwrap.wrap(text, width=width, initial_indent=indent,
                         subsequent_indent=" " * len(indent)) or [indent]


def bar(score: float, n: int = 10) -> str:
    filled = round(score * n)
    color = green if score >= 0.6 else yellow if score >= 0.3 else grey
    return color("█" * filled) + grey("░" * (n - filled))
