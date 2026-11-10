"""Tests for sync and search. Run: python -m unittest discover tests"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".claude" / "skills" / "kb" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import kb  # noqa: E402

FIRST = ROOT / "exports" / "kb_export_2026-10-01.csv"
SECOND = ROOT / "exports" / "kb_export_2026-11-09.csv"


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = kb.connect(Path(self.tmp.name) / "idx.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def count(self, table):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_first_load_adds_everything(self):
        res = kb.sync(self.conn, kb.read_export(FIRST), "first")
        self.assertEqual(len(res.added), 10)
        self.assertEqual(self.count("chunks"), 20)

    def test_resync_same_export_changes_nothing(self):
        kb.sync(self.conn, kb.read_export(FIRST), "first")
        res = kb.sync(self.conn, kb.read_export(FIRST), "again")
        self.assertEqual((res.added, res.updated, res.removed, res.unchanged), ([], [], [], 10))

    def test_second_export_is_incremental(self):
        kb.sync(self.conn, kb.read_export(FIRST), "first")
        res = kb.sync(self.conn, kb.read_export(SECOND), "second")
        self.assertEqual(res.added, ["Touchscreen not responding to taps"])
        self.assertEqual(res.updated, ["Black screen after a firmware update"])
        self.assertEqual(res.removed, ["Customer locked out of the content console"])
        self.assertEqual(res.unchanged, 8)
        self.assertEqual(self.count("chunks"), 20)   # removed article's chunks went with it

    def test_updated_article_content_is_searchable(self):
        kb.sync(self.conn, kb.read_export(FIRST), "first")
        kb.sync(self.conn, kb.read_export(SECOND), "second")
        steps, _ = kb.parse_body(kb.search(self.conn, "E-104")[0].body)
        self.assertIn("15 minutes", steps[0])


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "idx.db"
        conn = kb.connect(cls.path)
        kb.sync(conn, kb.read_export(SECOND), "test")
        conn.close()
        cls.conn = kb.connect(cls.path, readonly=True)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def top(self, q):
        return kb.search(self.conn, q)[0]

    def test_error_code_is_exact_and_ranked_first(self):
        hit = self.top("customer reports E-104")
        self.assertEqual((hit.title, hit.score, hit.matched),
                         ("Black screen after a firmware update", 1.0, "error code"))

    def test_natural_language_question(self):
        self.assertEqual(self.top("the screen went black after last night's update").title,
                         "Black screen after a firmware update")

    def test_tolerates_typos(self):
        self.assertEqual(self.top("screan is flickring with lines").title, "Screen flickers or shows lines")

    def test_unrelated_question_is_not_confident(self):
        self.assertLess(self.top("how do I bake a cake").score, 0.25)

    def test_index_is_read_only_for_search(self):
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM articles")

    def test_cli_json_contract(self):
        env = {**os.environ, "KB_INDEX_PATH": str(self.path)}
        out = subprocess.run([sys.executable, str(SCRIPTS / "search.py"), "no sound"],
                             capture_output=True, text=True, env=env, check=True)
        data = json.loads(out.stdout)
        self.assertTrue(data["confident_match"])
        self.assertEqual(data["results"][0]["title"], "Video plays but there is no sound")
        self.assertTrue(data["results"][0]["steps"])
        self.assertTrue(data["results"][0]["escalate_if"])


if __name__ == "__main__":
    unittest.main()
