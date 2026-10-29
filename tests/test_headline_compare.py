"""Offline regression tests for NewsAPI snapshot overlap summaries."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from headline_compare import compare, main


def response(*urls):
    return {"status": "ok", "articles": [{"url": url} for url in urls]}


class HeadlineCompareTests(unittest.TestCase):
    def test_overlap_new_removed_and_duplicate_urls(self):
        result = compare(
            response("https://news.test/a", "https://news.test/a", "https://news.test/b"),
            response("https://news.test/b", "https://news.test/c", "https://news.test/c"),
        )
        self.assertEqual(result, {
            "previous_unique_urls": 2,
            "current_unique_urls": 2,
            "overlapping_urls": 1,
            "new_urls": 1,
            "removed_urls": 1,
            "jaccard_similarity": 0.3333,
        })

    def test_invalid_urls_are_ignored(self):
        result = compare(
            {"status": "ok", "articles": [None, {"url": "javascript:alert(1)"}, {"url": "https://valid.test/a"}]},
            response("https://valid.test/a", "http://[bad"),
        )
        self.assertEqual(result["overlapping_urls"], 1)
        self.assertEqual(result["new_urls"], 0)

    def test_empty_snapshots_are_identical(self):
        result = compare(response(), response())
        self.assertEqual(result["jaccard_similarity"], 1.0)
        self.assertEqual(result["overlapping_urls"], 0)

    def test_invalid_newsapi_schema_is_rejected(self):
        for payload in (None, [], {"status": "error", "articles": []}, {"status": "ok"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                compare(payload, response())

    def test_cli_json_and_no_raw_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "old.json"
            new = Path(directory) / "new.json"
            old.write_text(json.dumps(response("https://private.test/story")), encoding="utf-8")
            new.write_text(json.dumps(response("https://private.test/story", "https://other.test/new")), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([str(old), str(new), "--json"]), 0)
            self.assertEqual(json.loads(output.getvalue())["new_urls"], 1)
            self.assertNotIn("private.test", output.getvalue())

    def test_malformed_input_never_echoes_file_contents_or_path(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "PRIVATE_SECRET_123.json"
            new = Path(directory) / "new.json"
            old.write_text('{"secret":"PRIVATE_SECRET_123"', encoding="utf-8")
            new.write_text(json.dumps(response()), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([str(old), str(new)]), 2)
            self.assertNotIn("PRIVATE_SECRET_123", output.getvalue())
            self.assertNotIn(str(old), output.getvalue())

    def test_oversized_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "old.json"
            new = Path(directory) / "new.json"
            old.write_bytes(b" " * 5_000_001)
            new.write_text(json.dumps(response()), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(old), str(new)]), 2)


if __name__ == "__main__":
    unittest.main()
