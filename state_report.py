"""Read-only, aggregate health report for the news bot's SQLite state."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import sqlite3
from pathlib import Path

STATUSES = ("seen", "failed", "dry_run", "posted")


def summarize_state(database: Path, max_attempts: int = 5) -> dict[str, object]:
    """Return status counts without exposing stored headlines, URLs or errors."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    if not database.is_file():
        raise ValueError("database does not exist")
    counts = dict.fromkeys(STATUSES, 0)
    exhausted = 0
    pending = 0
    # URI mode=ro prevents accidental database creation and writes.
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        for status, attempts in connection.execute("SELECT status, attempts FROM articles"):
            if status not in counts or not isinstance(attempts, int) or attempts < 0:
                raise ValueError("invalid article state")
            counts[status] += 1
            if status == "failed" and attempts >= max_attempts:
                exhausted += 1
            if status in ("seen", "dry_run") or (status == "failed" and attempts < max_attempts):
                pending += 1
    return {"total": sum(counts.values()), "statuses": counts,
            "retry_exhausted": exhausted, "eligible_for_attempt": pending}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect bot state without API calls or writes")
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parent / "data/news_bot.db")
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = summarize_state(args.db, args.max_attempts)
    except (OSError, sqlite3.DatabaseError, ValueError):
        # Avoid printing paths or database content in logs.
        print("Hata: bot durum veritabani okunamadi veya gecersiz.")
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Toplam: {report['total']} | Yeniden denenebilir: {report['eligible_for_attempt']} | "
              f"Deneme sinirina ulasan: {report['retry_exhausted']}")
        for status, count in report["statuses"].items():
            print(f"{status}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
