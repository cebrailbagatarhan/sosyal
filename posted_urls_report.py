"""Read-only summary of the news bot's previously posted URLs."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit


def summarize_urls(lines: list[str], top: int = 10) -> dict:
    """Count domains, duplicate entries and malformed URLs without network access."""
    if top < 1:
        raise ValueError("top must be positive")
    urls = [line.strip() for line in lines if line.strip()]
    domains: Counter[str] = Counter()
    invalid = 0
    for url in urls:
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
        except ValueError:
            host = None
            parsed = None
        if not parsed or parsed.scheme.lower() not in {"http", "https"} or not host or "." not in host:
            invalid += 1
            continue
        host = host.lower().removeprefix("www.")
        domains[host] += 1
    return {
        "total_entries": len(urls),
        "unique_urls": len(set(urls)),
        "duplicate_entries": len(urls) - len(set(urls)),
        "invalid_entries": invalid,
        "domains": [
            {"domain": domain, "posts": count}
            for domain, count in sorted(domains.items(), key=lambda pair: (-pair[1], pair[0]))[:top]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report posted URL counts without calling any APIs")
    parser.add_argument("--file", type=Path, default=Path(__file__).resolve().parent / "posted_urls.txt")
    parser.add_argument("--top", type=int, default=10, help="Number of top domains (default: 10)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if duplicate or invalid URLs are found")
    args = parser.parse_args(argv)
    if args.top < 1:
        parser.error("--top must be at least 1")
    try:
        lines = args.file.read_text(encoding="utf-8").splitlines() if args.file.exists() else []
    except (OSError, UnicodeError) as exc:
        parser.exit(2, f"Cannot read URL history: {exc}\n")
    result = summarize_urls(lines, top=args.top)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Entries: {result['total_entries']} | Unique: {result['unique_urls']} | "
              f"Duplicates: {result['duplicate_entries']} | Invalid: {result['invalid_entries']}")
        for item in result["domains"]:
            print(f"{item['domain']}: {item['posts']}")
    return int(args.strict and bool(result["duplicate_entries"] or result["invalid_entries"]))


if __name__ == "__main__":
    raise SystemExit(main())
