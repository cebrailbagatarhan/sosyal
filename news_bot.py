from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

import requests
import schedule
import tweepy
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from storage import ArticleStore, canonicalize_url


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
LEGACY_POSTED_URLS_PATH = BASE_DIR / "posted_urls.txt"
NEWS_API_URL = "https://newsapi.org/v2/top-headlines"
GROK_API_URL = "https://api.x.ai/v1/chat/completions"
MAX_TWEET_LENGTH = 280
X_SHORT_URL_LENGTH = 23

GROK_SYSTEM_PROMPT = (
    "Sen profesyonel bir haber editörüsün. Verilen haberi X için tarafsız bir "
    "Türkçe dille özetle ve en fazla iki ilgili hashtag ekle. Doğrulanmamış "
    "ayrıntı ekleme."
)

logger = logging.getLogger("x_news_bot")


@dataclass(frozen=True)
class Article:
    title: str
    description: str
    url: str


@dataclass(frozen=True)
class Config:
    news_api_key: str
    grok_api_key: str
    grok_model: str
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_secret: str = ""
    news_sources: str = "bbc-news,reuters"
    check_interval_hours: int = 2
    request_timeout_seconds: int = 30
    grok_min_interval_seconds: float = 1.0
    x_min_interval_seconds: float = 1.0
    max_article_attempts: int = 5
    database_path: Path = BASE_DIR / "data" / "news_bot.db"

    @classmethod
    def from_env(cls, require_x: bool = True) -> "Config":
        if ENV_PATH.exists():
            load_dotenv(ENV_PATH)
        required = ["NEWS_API_KEY", "GROK_API_KEY", "GROK_MODEL"]
        if require_x:
            required.extend(["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"])
        values = {key: os.getenv(key, "").strip() for key in required}
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise ValueError("Eksik ortam degiskenleri: " + ", ".join(sorted(missing)))
        placeholders = [
            key for key, value in values.items()
            if value.casefold().startswith(("your_", "senin_")) or "buraya_yaz" in value.casefold()
        ]
        if placeholders:
            raise ValueError("Ornek deger kalan degiskenler: " + ", ".join(sorted(placeholders)))

        return cls(
            news_api_key=values["NEWS_API_KEY"],
            grok_api_key=values["GROK_API_KEY"],
            grok_model=values["GROK_MODEL"],
            x_api_key=values.get("X_API_KEY", ""),
            x_api_secret=values.get("X_API_SECRET", ""),
            x_access_token=values.get("X_ACCESS_TOKEN", ""),
            x_access_secret=values.get("X_ACCESS_SECRET", ""),
            news_sources=os.getenv("NEWS_SOURCES", "bbc-news,reuters").strip(),
            check_interval_hours=_positive_int("CHECK_INTERVAL_HOURS", 2),
            request_timeout_seconds=_positive_int("REQUEST_TIMEOUT_SECONDS", 30),
            grok_min_interval_seconds=_non_negative_float("GROK_MIN_INTERVAL_SECONDS", 1.0),
            x_min_interval_seconds=_non_negative_float("X_MIN_INTERVAL_SECONDS", 1.0),
            max_article_attempts=_positive_int("MAX_ARTICLE_ATTEMPTS", 5),
            database_path=Path(os.getenv("BOT_DB_PATH", BASE_DIR / "data" / "news_bot.db")),
        )


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} pozitif olmali")
    return value


def _non_negative_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} negatif olamaz")
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in ("event", "article_url", "article_title", "tweet_id"):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


class RateGate:
    def __init__(self, minimum_interval_seconds: float) -> None:
        self.minimum_interval_seconds = minimum_interval_seconds
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            remaining = self.minimum_interval_seconds - (now - self._last_call)
            if remaining > 0:
                time.sleep(remaining)
            self._last_call = time.monotonic()


def build_retry_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    return session


class NewsAPIClient:
    def __init__(self, config: Config, session: requests.Session) -> None:
        self.config = config
        self.session = session

    def fetch_top_headlines(self) -> list[Article]:
        try:
            response = self.session.get(
                NEWS_API_URL,
                params={"sources": self.config.news_sources, "apiKey": self.config.news_api_key, "pageSize": 10},
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            raise RuntimeError("NewsAPI request failed") from error
        except ValueError as error:
            raise RuntimeError("NewsAPI returned invalid JSON") from error
        if payload.get("status") != "ok":
            raise RuntimeError(f"NewsAPI error: {payload.get('code', 'unknown')}")
        articles = []
        for item in payload.get("articles", []):
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            if title and url:
                articles.append(Article(title, str(item.get("description") or "").strip(), url))
        return articles


class GrokClient:
    def __init__(self, config: Config, session: requests.Session) -> None:
        self.config = config
        self.session = session
        self.rate_gate = RateGate(config.grok_min_interval_seconds)

    def summarize_article(self, article: Article) -> str:
        self.rate_gate.wait()
        payload = {
            "model": self.config.grok_model,
            "messages": [
                {"role": "system", "content": GROK_SYSTEM_PROMPT},
                {"role": "user", "content": f"Baslik: {article.title}\nAciklama: {article.description or 'Yok'}"},
            ],
            "temperature": 0.4,
        }
        try:
            response = self.session.post(
                GROK_API_URL,
                headers={"Authorization": f"Bearer {self.config.grok_api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as error:
            raise RuntimeError("Grok summarization failed") from error
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
        summary = collapse_whitespace(str(content))
        if not summary:
            raise RuntimeError("Grok returned an empty summary")
        return summary


class Poster(Protocol):
    def post_tweet(self, text: str) -> str: ...


class XClient:
    def __init__(self, config: Config) -> None:
        self.rate_gate = RateGate(config.x_min_interval_seconds)
        self.client = tweepy.Client(
            consumer_key=config.x_api_key,
            consumer_secret=config.x_api_secret,
            access_token=config.x_access_token,
            access_token_secret=config.x_access_secret,
            wait_on_rate_limit=True,
        )

    def post_tweet(self, text: str) -> str:
        self.rate_gate.wait()
        try:
            response = self.client.create_tweet(text=text, user_auth=True)
        except tweepy.TweepyException as error:
            raise RuntimeError("X post failed") from error
        tweet_id = str((response.data or {}).get("id", "")).strip()
        if not tweet_id:
            raise RuntimeError("X API returned no tweet ID")
        return tweet_id


class NewsBot:
    def __init__(self, config: Config, news_client: NewsAPIClient, grok_client: GrokClient, store: ArticleStore, poster: Poster | None, dry_run: bool) -> None:
        self.config = config
        self.news_client = news_client
        self.grok_client = grok_client
        self.store = store
        self.poster = poster
        self.dry_run = dry_run

    def run_once(self) -> bool:
        posted = self.store.posted_urls()
        articles = self.news_client.fetch_top_headlines()
        logger.info("News cycle fetched articles", extra={"event": "articles_fetched"})
        for article in articles:
            try:
                canonical_url = self.store.record_seen(article.url, article.title)
            except ValueError:
                logger.warning("Invalid article URL skipped", extra={"event": "invalid_url", "article_url": article.url})
                continue
            if canonical_url in posted or not self.store.can_attempt(canonical_url, self.config.max_article_attempts):
                continue
            try:
                summary = self.grok_client.summarize_article(article)
                tweet_text = build_tweet_text(summary, article.url)
                if self.dry_run:
                    self.store.mark_dry_run(canonical_url)
                    logger.info(
                        "Dry-run post preview: %s", tweet_text,
                        extra={"event": "dry_run", "article_url": canonical_url, "article_title": article.title},
                    )
                else:
                    if self.poster is None:
                        raise RuntimeError("Poster is not configured")
                    tweet_id = self.poster.post_tweet(tweet_text)
                    self.store.mark_posted(canonical_url, tweet_id)
                    logger.info("Post published", extra={"event": "posted", "article_url": canonical_url, "tweet_id": tweet_id})
                return True
            except Exception as error:
                self.store.mark_failed(canonical_url, f"{type(error).__name__}: {error}")
                logger.exception("Article processing failed", extra={"event": "article_failed", "article_url": canonical_url})
        logger.info("No publishable article", extra={"event": "no_article"})
        return False

    def run_forever(self) -> None:
        self._safe_cycle()
        schedule.every(self.config.check_interval_hours).hours.do(self._safe_cycle)
        while True:
            schedule.run_pending()
            time.sleep(30)

    def _safe_cycle(self) -> None:
        try:
            self.run_once()
        except Exception:
            logger.exception("News cycle failed", extra={"event": "cycle_failed"})


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def truncate_text(text: str, limit: int) -> str:
    clean = collapse_whitespace(text)
    if len(clean) <= limit:
        return clean
    if limit <= 3:
        return clean[:limit]
    return clean[: limit - 3].rstrip() + "..."


def build_tweet_text(summary: str, url: str) -> str:
    normalized = collapse_whitespace(summary)
    summary_budget = MAX_TWEET_LENGTH - X_SHORT_URL_LENGTH - 1
    if len(normalized) > summary_budget:
        normalized = truncate_text(normalized, summary_budget)
    return f"{normalized} {url}".strip()


def build_bot(config: Config, dry_run: bool) -> NewsBot:
    session = build_retry_session()
    store = ArticleStore(config.database_path)
    migrated = store.migrate_legacy_file(LEGACY_POSTED_URLS_PATH)
    if migrated:
        logger.info("Legacy URLs migrated", extra={"event": "legacy_migration"})
    return NewsBot(
        config,
        NewsAPIClient(config, session),
        GrokClient(config, session),
        store,
        None if dry_run else XClient(config),
        dry_run,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NewsAPI → Grok → X pipeline")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Summarize and preview without posting")
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()
    try:
        config = Config.from_env(require_x=not args.dry_run)
        bot = build_bot(config, args.dry_run)
        if args.once or args.dry_run:
            bot.run_once()
        else:
            bot.run_forever()
        return 0
    except KeyboardInterrupt:
        logger.info("Bot stopped by user", extra={"event": "stopped"})
        return 130
    except Exception:
        logger.exception("Bot startup failed", extra={"event": "startup_failed"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

