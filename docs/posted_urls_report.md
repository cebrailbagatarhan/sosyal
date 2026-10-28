# Posted URL history report

Use the read-only, offline report to see how many URLs the news bot has
recorded, how many entries are duplicates, and which source domains appear most.

`python posted_urls_report.py --file posted_urls.txt --top 5`

For automation, add `--json`. If the history file does not yet exist, the report
shows zero entries. No environment variables, API keys, Grok calls or X posts
are needed. The tool does not edit the history file or display individual URLs.

The report is designed for the existing `posted_urls.txt` format on `main`.
An open PR proposes a SQLite-backed storage replacement; that storage format
would need a separate adapter before this report could inspect it.

To make offline checks fail when the history contains duplicate or malformed
URLs, add `--strict` (exit code 1 for issues, 0 for clean or missing history).
Without `--strict`, reporting remains informational and exits 0.
