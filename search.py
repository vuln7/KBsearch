"""Convenience entry point: same as .claude/skills/kb/scripts/search.py."""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / ".claude" / "skills" / "kb" / "scripts" / "search.py"),
    run_name="__main__",
)
