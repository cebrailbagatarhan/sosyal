import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from headline_audit import audit_headlines


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "headline_audit.py"


def article(title="News", url="https://news.example/a", source="BBC"):
    return {"title": title, "url": url, "source": {"name": source}}


class HeadlineAuditTests(unittest.TestCase):
    def test_valid_articles_and_source_diversity(self):
        result = audit_headlines({"status": "ok", "articles": [
            article(), article("Second", "https://other.example/b", "Reuters"),
        ]})
        self.assertEqual(result["articles"], 2)
        self.assertEqual(result["usable"], 2)
        self.assertEqual(result["distinct_sources"], 2)
        self.assertEqual(result["duplicate_urls"], 0)

    def test_missing_titles_urls_and_invalid_entries(self):
        result = audit_headlines({"status": "ok", "articles": [
            article("", "https://news.example/a"),
            article("Valid title", "javascript:alert(1)"),
            article("Bad URL", "https://[bad"),
            None,
        ]})
        self.assertEqual(result["missing_titles"], 1)
        self.assertEqual(result["invalid_urls"], 2)
        self.assertEqual(result["invalid_entries"], 1)
        self.assertEqual(result["usable"], 0)

    def test_exact_duplicate_urls_are_reported_without_disclosing_them(self):
        result = audit_headlines({"status": "ok", "articles": [
            article(), article("Another title"), article("Third", "http://news.example/b"),
        ]})
        self.assertEqual(result["duplicate_urls"], 1)
        self.assertEqual(result["usable"], 3)
        self.assertNotIn("news.example", str(result))

    def test_rejects_unexpected_top_level_payload(self):
        for value in (None, [], {"status": "error", "articles": []}, {"status": "ok"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit_headlines(value)

    def test_cli_json_and_strict_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "response.json"
            file.write_text(json.dumps({"status": "ok", "articles": [article()]}), encoding="utf-8")
            good = subprocess.run(
                [sys.executable, str(SCRIPT), str(file), "--json", "--strict"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(json.loads(good.stdout)["usable"], 1)
            file.write_text(json.dumps({"status": "ok", "articles": [article(), article()]}), encoding="utf-8")
            duplicate = subprocess.run(
                [sys.executable, str(SCRIPT), str(file), "--json", "--strict"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(duplicate.returncode, 1)
            self.assertEqual(json.loads(duplicate.stdout)["duplicate_urls"], 1)

    def test_malformed_json_does_not_echo_private_input(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "response.json"
            file.write_text('{"secret": "PRIVATE_TOKEN_123"', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(file)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("PRIVATE_TOKEN_123", result.stdout + result.stderr)
            self.assertNotIn(str(file), result.stdout + result.stderr)

    def test_large_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "response.json"
            file.write_bytes(b" " * 5_000_001)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(file)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
