#!/usr/bin/env python3
"""Audit a saved NewsAPI top-headlines response without network access or posting.

Usage: python headline_audit.py response.json [--json] [--strict]
The report contains only aggregate counts, never article titles, URLs or API keys.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit


def _valid_url(value: object) -> bool:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.port != 0
        )
    except ValueError:
        return False


def audit_headlines(payload: object) -> dict[str, int]:
    """Summarize quality issues without including any raw article content."""
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise ValueError("Beklenen NewsAPI status=ok yaniti bulunamadi.")
    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise ValueError("NewsAPI articles alani bir liste olmali.")

    report = {
        "articles": len(articles),
        "usable": 0,
        "missing_titles": 0,
        "missing_descriptions": 0,
        "invalid_urls": 0,
        "duplicate_urls": 0,
        "invalid_entries": 0,
        "distinct_sources": 0,
    }
    seen_urls: set[str] = set()
    sources: set[str] = set()
    for article in articles:
        if not isinstance(article, dict):
            report["invalid_entries"] += 1
            continue
        title = article.get("title")
        description = article.get("description")
        url = article.get("url")
        title_ok = isinstance(title, str) and bool(title.strip())
        url_ok = _valid_url(url)
        if not title_ok:
            report["missing_titles"] += 1
        if not isinstance(description, str) or not description.strip():
            report["missing_descriptions"] += 1
        if not url_ok:
            report["invalid_urls"] += 1
        if url_ok:
            normalized_url = url.strip()
            if normalized_url in seen_urls:
                report["duplicate_urls"] += 1
            seen_urls.add(normalized_url)
        if title_ok and url_ok:
            report["usable"] += 1
        source = article.get("source")
        if isinstance(source, dict) and isinstance(source.get("name"), str):
            name = source["name"].strip()
            if name:
                sources.add(name)
    report["distinct_sources"] = len(sources)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="Saved NewsAPI JSON response (never sent anywhere)")
    parser.add_argument("--json", action="store_true", help="Machine-readable aggregate counts")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if malformed, duplicate or unusable articles are found")
    args = parser.parse_args(argv)
    try:
        # Bound the input to avoid unexpectedly loading enormous files.
        with args.file.open("rb") as stream:
            raw = stream.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError("JSON dosyasi 5 MB sinirini asiyor.")
        report = audit_headlines(json.loads(raw))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        # Do not echo exception details: API responses and filenames can contain secrets.
        print("Hata: gecerli bir NewsAPI JSON dosyasi okunamadi.")
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        for name, count in report.items():
            print(f"{name}: {count}")

    issues = ("missing_titles", "invalid_urls", "duplicate_urls", "invalid_entries")
    return int(args.strict and any(report[key] for key in issues))


if __name__ == "__main__":
    raise SystemExit(main())
