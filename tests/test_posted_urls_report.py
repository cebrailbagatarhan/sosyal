"""Standard-library tests for read-only posted URL statistics."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from posted_urls_report import main, summarize_urls


class PostedURLReportTests(unittest.TestCase):
    def test_domains_duplicates_and_invalid_urls(self):
        result = summarize_urls([
            "https://www.example.com/a", "https://www.example.com/a",
            "http://EXAMPLE.com/b", "https://news.test/story", "not-a-url", "",
        ])
        self.assertEqual(result["total_entries"], 5)
        self.assertEqual(result["unique_urls"], 4)
        self.assertEqual(result["duplicate_entries"], 1)
        self.assertEqual(result["invalid_entries"], 1)
        self.assertEqual(result["domains"][0], {"domain": "example.com", "posts": 3})
        self.assertNotIn("/a", json.dumps(result))

    def test_top_limit_and_deterministic_tie_order(self):
        result = summarize_urls(["https://z.test/a", "https://a.test/b"], top=1)
        self.assertEqual(result["domains"], [{"domain": "a.test", "posts": 1}])

    def test_invalid_port_or_ipv6_does_not_crash(self):
        result = summarize_urls(["http://[broken", "http://user:pass@example.com/path"])
        self.assertEqual(result["invalid_entries"], 1)
        self.assertEqual(result["domains"], [{"domain": "example.com", "posts": 1}])

    def test_cli_json_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "urls.txt"
            path.write_text("https://news.test/one\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--file", str(path), "--json"]), 0)
            self.assertEqual(json.loads(output.getvalue())["total_entries"], 1)

    def test_missing_history_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--file", str(Path(directory) / "missing.txt")]), 0)
            self.assertIn("Entries: 0", output.getvalue())

    def test_strict_returns_failure_for_duplicate_or_invalid_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "urls.txt"
            for urls in (
                ("https://news.test/one", "https://news.test/one"),
                ("https://news.test/one", "not-a-url"),
            ):
                path.write_text("\n".join(urls) + "\n", encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--file", str(path), "--strict"]), 1)
                    self.assertEqual(main(["--file", str(path)]), 0)

    def test_strict_accepts_clean_or_missing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "urls.txt"
            path.write_text("\n".join([
                "https://news.test/one", "https://other.test/two"
            ]) + "\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--file", str(path), "--strict", "--json"]), 0)
            self.assertEqual(json.loads(output.getvalue())["invalid_entries"], 0)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--file", str(path.parent / "missing.txt"), "--strict"]), 0)

    def test_invalid_top_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main(["--top", "0"])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
