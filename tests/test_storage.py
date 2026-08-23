import tempfile
import unittest
from pathlib import Path

from storage import ArticleStore, canonicalize_url


class ArticleStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ArticleStore(Path(self.temporary.name) / "state.db")

    def tearDown(self):
        self.temporary.cleanup()

    def test_canonical_url_removes_tracking_and_fragment(self):
        first = canonicalize_url("HTTPS://Example.com/news?id=2&utm_source=x#section")
        second = canonicalize_url("https://example.com/news?utm_medium=social&id=2")
        self.assertEqual(first, "https://example.com/news?id=2")
        self.assertEqual(first, second)

    def test_posted_state_persists_and_deduplicates(self):
        canonical = self.store.record_seen("https://example.com/a?utm_source=x", "A")
        self.store.mark_posted(canonical, "tweet-1")
        self.store.record_seen("https://example.com/a", "Updated title")
        self.assertIn(canonical, self.store.posted_urls())
        row = self.store.get("https://example.com/a")
        self.assertEqual(row["status"], "posted")
        self.assertEqual(row["tweet_id"], "tweet-1")

    def test_failed_attempts_are_limited(self):
        canonical = self.store.record_seen("https://example.com/failure", "Failure")
        self.store.mark_failed(canonical, "temporary failure")
        self.assertTrue(self.store.can_attempt(canonical, 2))
        self.store.mark_failed(canonical, "second failure")
        self.assertFalse(self.store.can_attempt(canonical, 2))

    def test_dry_run_does_not_consume_publish_attempts(self):
        canonical = self.store.record_seen("https://example.com/preview", "Preview")
        self.store.mark_dry_run(canonical)
        self.assertTrue(self.store.can_attempt(canonical, 1))
        self.assertEqual(self.store.get(canonical)["attempts"], 0)

    def test_legacy_file_is_migrated_idempotently(self):
        legacy = Path(self.temporary.name) / "posted_urls.txt"
        legacy.write_text("https://example.com/old?utm_source=x\n", encoding="utf-8")
        self.assertEqual(self.store.migrate_legacy_file(legacy), 1)
        self.assertEqual(self.store.migrate_legacy_file(legacy), 0)
        self.assertIn("https://example.com/old", self.store.posted_urls())


if __name__ == "__main__":
    unittest.main()
