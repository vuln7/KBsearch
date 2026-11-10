"""Render docs/demo.gif: a /kb session in Claude Code, drawn as an ink-on-paper terminal.

Dev tool; needs Pillow (pip install pillow) and the Consolas fonts that ship with Windows.

What is real: every answer, score and step in the GIF comes from running the skill's
search script against a freshly synced index. What is recreated: the chat frame around it.
The reply is laid out in the format SKILL.md tells Claude to use.

    python docs/make_demo_gif.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "demo.gif"
SEARCH = ".claude/skills/kb/scripts/search.py"
QUESTIONS = [
    "screen went black after last night's update",
    "kiosk shows E-620, taps do nothing",
]

# palette shared with the showcase site
PAPER, SHEET, INK = (247, 245, 239), (251, 250, 246), (36, 35, 31)
DIM, RULE, MAUVE, BAR_TEXT = (98, 94, 86), (201, 196, 184), (120, 95, 105), (214, 209, 196)

FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
SIZE = 14
REG = ImageFont.truetype(str(FONTS / "consola.ttf"), SIZE)
BOLD = ImageFont.truetype(str(FONTS / "consolab.ttf"), SIZE)
CW = REG.getlength("M")
LH = 21

W, H = 780, 640
MARGIN, BAR_H, PAD = 14, 30, 18
LEFT = MARGIN + PAD                    # text left edge inside the window
RIGHT = W - MARGIN - PAD               # text right edge
INDENT = 18                            # event body indent (after the dot)
COLS = int((RIGHT - LEFT - INDENT) / CW)


# ------------------------------------------------------------------ real data

def run_search(question: str, env: dict) -> dict:
    out = subprocess.run([sys.executable, SEARCH, question], cwd=ROOT, env=env,
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


def collect() -> list[dict]:
    """Sync both sample exports into a throwaway index, then run each question for real."""
    with tempfile.TemporaryDirectory() as tmp:
        index = str(Path(tmp) / "kb_index.db")
        env = {**os.environ, "KB_INDEX_PATH": index, "PYTHONIOENCODING": "utf-8", "FORCE_COLOR": "0"}
        for export in sorted((ROOT / "exports").glob("*.csv")):
            subprocess.run([sys.executable, "sync.py", str(export), "--index", index],
                           cwd=ROOT, env=env, check=True, capture_output=True)
        return [run_search(q, env) for q in QUESTIONS]


# ------------------------------------------------------------------ drawing

class Canvas:
    """One frame. Rows are placed top-down with a running y cursor."""

    def __init__(self):
        self.img = Image.new("RGB", (W, H), PAPER)
        self.d = ImageDraw.Draw(self.img)
        x0, y0, x1, y1 = MARGIN, MARGIN, W - MARGIN, H - MARGIN
        self.d.rectangle((x0, y0, x1, y1), fill=SHEET, outline=INK)
        self.d.rectangle((x0, y0, x1, y0 + BAR_H), fill=INK)
        for i in range(3):
            cx = x0 + 18 + i * 16
            self.d.ellipse((cx - 5, y0 + BAR_H // 2 - 5, cx + 5, y0 + BAR_H // 2 + 5), outline=BAR_TEXT)
        title = "claude code · support"
        self.d.text(((W - REG.getlength(title)) / 2, y0 + BAR_H // 2 - SIZE // 2 - 1), title, font=REG, fill=BAR_TEXT)
        self.y = y0 + BAR_H + PAD - 4

    def text(self, x: float, segments: list[tuple], y: int | None = None) -> float:
        """Draw (text, colour, bold) segments on one line; returns the end x."""
        y = self.y if y is None else y
        for chunk, colour, bold in segments:
            font = BOLD if bold else REG
            self.d.text((x, y + 3), chunk, font=font, fill=colour)
            x += font.getlength(chunk)
        return x

    def prompt(self, command: str, rest: str, caret: bool):
        top = self.y
        self.d.rectangle((LEFT, top, RIGHT, top + LH + 10), outline=INK)
        end = self.text(LEFT + 10, [("> ", DIM, False), (command, INK, True), (rest, INK, False)], top + 5)
        if caret:
            self.d.rectangle((end + 1, top + 8, end + CW - 1, top + LH + 3), fill=INK)
        self.y = top + LH + 10 + 12

    def dot(self):
        self.d.ellipse((LEFT + 2, self.y + 8, LEFT + 8, self.y + 14), fill=INK)

    def line(self, segments: list[tuple], indent: float = INDENT):
        self.text(LEFT + indent, segments)
        self.y += LH

    def hood(self, question: str, results: list[dict], shown: int, grow: float, note: str | None):
        """The solid ink bar, then the open panel with the command and ranked matches."""
        x0, x1 = LEFT + INDENT, RIGHT
        top = self.y + 4
        self.d.rectangle((x0, top, x1, top + LH + 8), fill=INK)
        self.text(x0 + 10, [("under the hood", SHEET, True), ("  the python script that ran", BAR_TEXT, False)], top + 4)
        hide_x = x1 - 10 - REG.getlength("hide")
        self.d.text((hide_x, top + 7), "hide", font=REG, fill=SHEET)
        self.d.line((hide_x, top + 7 + SIZE + 2, hide_x + REG.getlength("hide"), top + 7 + SIZE + 2), fill=SHEET)

        body_top = top + LH + 8
        rows = 1 + 2 * len(results) + 1
        body_bottom = body_top + 10 + rows * LH + 12
        self.d.rectangle((x0, body_top, x1, body_bottom), fill=PAPER, outline=INK)
        y = body_top + 10
        self.text(x0 + 12, [("$ ", DIM, False), (f'python scripts/search.py "{question}"', INK, False)], y)
        y += LH + 4
        for i, hit in enumerate(results[:shown]):
            bx, bw = x0 + 12, 86
            for dash in range(0, bw, 4):                       # dotted track
                self.d.rectangle((bx + dash, y + 7, bx + dash + 1, y + 15), fill=RULE)
            fill = hit["score"] * (grow if i == shown - 1 else 1.0)
            if fill > 0:
                self.d.rectangle((bx, y + 7, bx + max(2, int(bw * fill)), y + 15), fill=INK)
            self.text(bx + bw + 10, [(f"{hit['score']:.2f}  ", DIM, False), (hit["title"], INK, i == 0)], y)
            meta = " · ".join(v for v in (hit["product"], hit["category"], hit["error_code"]) if v)
            if hit["matched_on"] == "error code":
                meta += " · matched on the exact code"
            self.text(bx + bw + 10 + REG.getlength("0.00  "), [(meta, DIM, False)], y + LH - 3)
            y += 2 * LH
        if note:
            self.text(x0 + 12, [(note, DIM, False)], body_bottom - LH - 6)
        self.y = body_bottom + 12


def build_frames(sessions: list[dict]) -> tuple[list[Image.Image], list[int]]:
    frames, durations = [], []

    def emit(draw, ms):
        canvas = Canvas()
        draw(canvas)
        frames.append(canvas.img)
        durations.append(ms)

    for data in sessions:
        question, results = data["query"], data["results"]
        top = results[0]
        exact = top["matched_on"] == "error code"
        tool = (f" · exact match on error code {top['error_code']}" if exact
                else f" · searched the knowledge base · {len(results)} matches")
        note = ("an exact error code outranks similarity" if exact
                else "vector search · confident match" if data["confident_match"] else "no confident match")
        note += f" · returned the steps for #{top['article_id']}"

        answer: list[list[tuple]] = []
        for n, step in enumerate(top["steps"], 1):
            wrapped = textwrap.wrap(step, COLS - 4)
            answer.append([(f"{n}. ", DIM, False), (wrapped[0], INK, False)])
            answer += [[("   " + more, INK, False)] for more in wrapped[1:]]
        esc = textwrap.wrap("Escalate if " + top["escalate_if"][0].lower() + top["escalate_if"][1:], COLS - 1)
        esc_lines = [[("Escalate if", MAUVE, True), (esc[0][len("Escalate if"):], INK, False)]]
        esc_lines += [[(more, INK, False)] for more in esc[1:]]

        def scene(typed, caret, tool_on, hits, grow, note_on, answer_rows, esc_on, next_prompt):
            def draw(c: Canvas):
                c.prompt("/kb"[:typed], (" " + question)[:max(0, typed - 3)], caret)
                if not tool_on:
                    return
                c.dot()
                c.line([("kb", INK, True), (tool, DIM, False)])
                c.hood(question, results, hits, grow, note if note_on else None)
                if answer_rows < 0:
                    return
                c.dot()
                c.line([(top["title"], INK, True), (f"  (article #{top['article_id']})", DIM, False)])
                for row in answer[:answer_rows]:
                    c.line(row)
                if esc_on:
                    c.y += 6
                    for row in esc_lines:
                        c.line(row)
                if next_prompt:
                    c.y += 10
                    c.prompt("", "", True)
            return draw

        full = 3 + 1 + len(question)
        emit(scene(0, True, False, 0, 0, False, -1, False, False), 600)
        for typed in range(2, full + 1, 2):
            emit(scene(typed, True, False, 0, 0, False, -1, False, False), 60)
        emit(scene(full, True, False, 0, 0, False, -1, False, False), 450)
        emit(scene(full, False, True, 0, 0, False, -1, False, False), 350)
        for hits in range(1, len(results) + 1):
            for grow in (0.35, 0.75, 1.0):
                emit(scene(full, False, True, hits, grow, False, -1, False, False), 70)
        emit(scene(full, False, True, len(results), 1, True, -1, False, False), 1300)
        emit(scene(full, False, True, len(results), 1, True, 0, False, False), 250)
        for rows in range(1, len(answer) + 1):
            emit(scene(full, False, True, len(results), 1, True, rows, False, False), 110)
        emit(scene(full, False, True, len(results), 1, True, len(answer), True, False), 500)
        emit(scene(full, False, True, len(results), 1, True, len(answer), True, True), 4200)
    return frames, durations


def main() -> None:
    frames, durations = build_frames(collect())
    OUT.parent.mkdir(exist_ok=True)
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, optimize=True, disposal=1)
    print(f"wrote {OUT} ({len(frames)} frames, {OUT.stat().st_size // 1024} KB, {sum(durations) / 1000:.1f}s)")


if __name__ == "__main__":
    main()
