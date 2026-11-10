"""Knowledge-base vector index: embedding, storage, sync and search.

Self-contained (Python standard library only) so the demo runs anywhere with no API keys.

* Embedder: feature-hashed bag of words + word bigrams + character trigrams, L2-normalised.
  Each article's vector depends only on its own text, so a sync re-embeds only what changed.
  Swap `embed()` for a real embedding model (OpenAI, Voyage, sentence-transformers...) in production.
* Store: SQLite file holding articles, chunks and float32 vectors (a minimal local vector store).
* Search: hybrid - exact error-code match first, then cosine similarity over chunk vectors.
"""

from __future__ import annotations

import array
import csv
import hashlib
import math
import os
import re
import sqlite3
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

DIM = 2048
STOPWORDS = frozenset(
    "a an and are as at be but by for from has have i if in into is it its my of on or our so "
    "that the their them then there they this to was we what when where which while who why will with "
    "you your customer customers says said".split()
)
ERROR_CODE_RE = re.compile(r"\b[Ee]-?\d{3}\b")


# ---------------------------------------------------------------- embedding

def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:-[0-9]+)?", text.lower()) if t not in STOPWORDS]


def _add(vec: list[float], feature: str, weight: float) -> None:
    h = zlib.crc32(feature.encode("utf-8"))
    vec[h % DIM] += weight if (h >> 31) & 1 == 0 else -weight


def embed(text: str) -> array.array:
    """Hashed sparse features -> dense float32 vector of length DIM, unit length."""
    vec = [0.0] * DIM
    toks = _tokens(text)
    for t in toks:
        _add(vec, "w:" + t, 1.0)
        padded = f"^{t}$"
        for i in range(len(padded) - 2):          # char trigrams tolerate typos ("screan")
            _add(vec, "c:" + padded[i:i + 3], 0.35)
    for a, b in zip(toks, toks[1:]):
        _add(vec, f"b:{a} {b}", 0.8)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return array.array("f", (v / norm for v in vec))


def cosine(a: array.array, b: array.array) -> float:
    return sum(x * y for x, y in zip(a, b))   # both unit length


# ---------------------------------------------------------------- articles

@dataclass
class Article:
    article_id: int
    title: str
    product: str
    category: str
    symptoms: str
    error_code: str
    body: str
    updated_at: str

    @property
    def content_hash(self) -> str:
        raw = "\x1f".join([self.title, self.product, self.category, self.symptoms, self.error_code, self.body])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def chunks(self) -> list[tuple[str, str]]:
        """(section, text) pairs. Overview carries the symptom language; steps carry the fix."""
        steps = self.body.split("## Escalate if")[0].replace("## Steps", "").strip()
        return [
            ("overview", f"{self.title}. {self.product}. {self.category}. {self.symptoms}. {self.error_code}"),
            ("steps", f"{self.title}. {steps}"),
        ]


def read_export(path: Path) -> list[Article]:
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    required = {"article_id", "title", "body"}
    if rows and not required.issubset(rows[0]):
        raise SystemExit(f"{path.name}: missing columns {sorted(required - set(rows[0]))}")
    return [
        Article(int(r["article_id"]), r["title"].strip(), r.get("product", "").strip(),
                r.get("category", "").strip(), r.get("symptoms", "").strip(),
                r.get("error_code", "").strip().upper(), r["body"].strip(), r.get("updated_at", "").strip())
        for r in rows if r.get("title", "").strip()
    ]


# ---------------------------------------------------------------- store

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    article_id INTEGER PRIMARY KEY, title TEXT, product TEXT, category TEXT, symptoms TEXT,
    error_code TEXT, body TEXT, updated_at TEXT, content_hash TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    article_id INTEGER REFERENCES articles(article_id) ON DELETE CASCADE,
    section TEXT, text TEXT, vector BLOB
);
CREATE TABLE IF NOT EXISTS sync_log (
    run_at TEXT DEFAULT CURRENT_TIMESTAMP, source TEXT, added INTEGER, updated INTEGER,
    removed INTEGER, unchanged INTEGER
);
"""


def default_index_path() -> Path:
    """KB_INDEX_PATH if set, else the nearest kb_index.db above this script, else ./kb_index.db."""
    if os.environ.get("KB_INDEX_PATH"):
        return Path(os.environ["KB_INDEX_PATH"])
    for parent in Path(__file__).resolve().parents:
        if (parent / "kb_index.db").exists():
            return parent / "kb_index.db"
    return Path.cwd() / "kb_index.db"


def connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        if not path.exists():
            raise SystemExit(f"No index at {path}. Run sync.py first.")
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)
        conn.executescript(SCHEMA)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@dataclass
class SyncResult:
    added: list[str]
    updated: list[str]
    removed: list[str]
    unchanged: int


def sync(conn: sqlite3.Connection, articles: list[Article],
         source: str) -> SyncResult:
    """Make the index match `articles`, re-embedding only new or changed articles."""
    existing = {aid: (h, title) for aid, h, title in conn.execute(
        "SELECT article_id, content_hash, title FROM articles")}
    incoming = {a.article_id: a for a in articles}
    res = SyncResult([], [], [], 0)

    with conn:
        for aid in existing.keys() - incoming.keys():
            conn.execute("DELETE FROM chunks WHERE article_id = ?", (aid,))
            conn.execute("DELETE FROM articles WHERE article_id = ?", (aid,))
            res.removed.append(existing[aid][1])
        for aid, art in incoming.items():
            h = art.content_hash
            if aid not in existing:
                res.added.append(art.title)
            elif existing[aid][0] == h:
                res.unchanged += 1
                continue
            else:
                conn.execute("DELETE FROM chunks WHERE article_id = ?", (aid,))
                res.updated.append(art.title)
            row = {**asdict(art), "content_hash": h}
            conn.execute(f"INSERT OR REPLACE INTO articles ({', '.join(row)}) "
                         f"VALUES ({', '.join(':' + c for c in row)})", row)
            conn.executemany(
                "INSERT INTO chunks (article_id, section, text, vector) VALUES (?,?,?,?)",
                [(aid, sec, txt, embed(txt).tobytes()) for sec, txt in art.chunks()])
        conn.execute(
            "INSERT INTO sync_log (source, added, updated, removed, unchanged) "
            "VALUES (?,?,?,?,?)",
            (source, len(res.added), len(res.updated), len(res.removed), res.unchanged))
    return res


# ---------------------------------------------------------------- search

@dataclass
class Hit:
    article_id: int
    title: str
    product: str
    category: str
    error_code: str
    body: str
    score: float
    matched: str          # 'error code' or the best-matching chunk section


def search(conn: sqlite3.Connection, query: str, k: int = 3) -> list[Hit]:
    """Top k articles: an exact error code first, then by best chunk similarity."""
    qvec = embed(query)
    codes = {re.sub(r"^[Ee]-?", "E-", c) for c in ERROR_CODE_RE.findall(query)}

    # brute force; fine for a few hundred articles (see README for timings)
    best: dict[int, tuple[float, str]] = {}
    for aid, section, blob in conn.execute(
            "SELECT article_id, section, vector FROM chunks"):
        vec = array.array("f")
        vec.frombytes(blob)
        score = cosine(qvec, vec)
        if aid not in best or score > best[aid][0]:
            best[aid] = (score, section)

    if codes:  # exact error-code match beats similarity
        marks = ",".join("?" * len(codes))
        for (aid,) in conn.execute(
                f"SELECT article_id FROM articles WHERE error_code IN ({marks})",
                sorted(codes)):
            best[aid] = (1.0, "error code")

    top = sorted(best.items(), key=lambda item: item[1][0], reverse=True)[:k]
    if not top:
        return []
    rows = {r[0]: r for r in conn.execute(
        f"SELECT article_id, title, product, category, error_code, body "
        f"FROM articles WHERE article_id IN ({','.join('?' * len(top))})",
        [aid for aid, _ in top])}
    return [Hit(*rows[aid], score=max(score, 0.0), matched=section)
            for aid, (score, section) in top]


def parse_body(body: str) -> tuple[list[str], str]:
    """Split an article body into (numbered steps, escalation text)."""
    steps_part, _, esc = body.partition("## Escalate if")
    steps = [re.sub(r"^\d+\.\s*", "", l).strip()
             for l in steps_part.splitlines() if re.match(r"^\s*\d+\.", l)]
    return steps, " ".join(esc.split())
