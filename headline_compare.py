#!/usr/bin/env python3
"""Compare two saved NewsAPI responses without network requests or raw URL output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from headline_audit import _valid_url

MAX_BYTES = 5_000_000


def _urls(payload: object) -> set[str]:
    """Return distinct valid article URLs; never expose titles or URLs in reports."""
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise ValueError("Expected a successful NewsAPI response")
    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise ValueError("Expected an articles list")
    return {
        article["url"]
        for article in articles
        if isinstance(article, dict) and _valid_url(article.get("url"))
    }


def compare(old: object, new: object) -> dict[str, int | float]:
    """Summarize URL churn between snapshots, counting each URL only once."""
    previous, current = _urls(old), _urls(new)
    overlap = len(previous & current)
    union = len(previous | current)
    return {
        "previous_unique_urls": len(previous),
        "current_unique_urls": len(current),
        "overlapping_urls": overlap,
        "new_urls": len(current - previous),
        "removed_urls": len(previous - current),
        "jaccard_similarity": round(overlap / union, 4) if union else 1.0,
    }


def _load(path: Path) -> object:
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("JSON file exceeds size limit")
    return json.loads(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare saved NewsAPI snapshots offline")
    parser.add_argument("previous", type=Path, help="Older NewsAPI JSON response")
    parser.add_argument("current", type=Path, help="Newer NewsAPI JSON response")
    parser.add_argument("--json", action="store_true", help="Print aggregate JSON")
    args = parser.parse_args(argv)
    try:
        result = compare(_load(args.previous), _load(args.current))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        # Do not echo paths or malformed input: saved responses may be sensitive.
        print("Error: could not compare two valid NewsAPI JSON snapshots.")
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
