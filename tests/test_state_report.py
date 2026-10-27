import contextlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from state_report import main, summarize_state


class StateReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "bot state.db"
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE articles (status TEXT, attempts INTEGER, title TEXT, canonical_url TEXT)")
            connection.executemany("INSERT INTO articles VALUES (?, ?, ?, ?)", [
                ("seen", 0, "secret title", "https://example.org/secret"),
                ("dry_run", 0, "secret title", "https://example.org/secret"),
                ("failed", 2, "secret title", "https://example.org/secret"),
                ("failed", 5, "secret title", "https://example.org/secret"),
                ("posted", 1, "secret title", "https://example.org/secret"),
            ])

    def test_counts_and_retry_limit(self):
        report = summarize_state(self.path)
        self.assertEqual(report["total"], 5)
        self.assertEqual(report["statuses"], {"seen": 1, "failed": 2, "dry_run": 1, "posted": 1})
        self.assertEqual(report["retry_exhausted"], 1)
        self.assertEqual(report["eligible_for_attempt"], 3)
        self.assertEqual(summarize_state(self.path, 2)["retry_exhausted"], 2)

    def test_no_sensitive_values_in_json_output(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--db", str(self.path), "--json"]), 0)
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("example.org", output.getvalue())

    def test_missing_database_does_not_create_file(self):
        missing = Path(self.temp.name) / "missing.db"
        with self.assertRaises(ValueError):
            summarize_state(missing)
        self.assertFalse(missing.exists())

    def test_bad_attempt_limit_and_invalid_state(self):
        with self.assertRaises(ValueError):
            summarize_state(self.path, 0)
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT INTO articles VALUES ('invalid', 0, 'x', 'x')")
        with self.assertRaises(ValueError):
            summarize_state(self.path)

    def test_corrupt_schema_returns_safe_error(self):
        broken = Path(self.temp.name) / "broken.db"
        broken.write_bytes(b"not sqlite")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--db", str(broken)]), 2)
        self.assertNotIn(str(broken), output.getvalue())


if __name__ == "__main__":
    unittest.main()
