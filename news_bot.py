from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests
import schedule
import tweepy
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
POSTED_URLS_PATH = BASE_DIR / "posted_urls.txt"

NEWS_API_URL = "https://newsapi.org/v2/top-headlines"
GROK_API_URL = "https://api.x.ai/v1/chat/completions"
NEWS_SOURCES = "bbc-news,reuters"
GROK_MODEL = "grok-beta"
CHECK_INTERVAL_HOURS = 2
REQUEST_TIMEOUT_SECONDS = 30
MAX_TWEET_LENGTH = 280
X_SHORT_URL_LENGTH = 23

GROK_SYSTEM_PROMPT = (
    "Sen profesyonel bir haber editörüsün. Sana verilen haberi X (Twitter) "
    "platformu için en fazla 280 karakter olacak şekilde, dikkat çekici, "
    "tarafsız bir Türkçe dille özetle ve 1-2 uygun hashtag ekle."
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
    x_api_key: str
    x_api_secret: str
    x_access_token: str
    x_access_secret: str
    news_sources: str = NEWS_SOURCES
    grok_model: str = GROK_MODEL

    @classmethod
    def from_env(cls) -> "Config":
        if not ENV_PATH.exists():
            raise FileNotFoundError(f".env dosyasi bulunamadi: {ENV_PATH}")

        load_dotenv(ENV_PATH)

        required_keys = [
            "NEWS_API_KEY",
            "GROK_API_KEY",
            "X_API_KEY",
            "X_API_SECRET",
            "X_ACCESS_TOKEN",
            "X_ACCESS_SECRET",
        ]

        values = {key: os.getenv(key, "").strip() for key in required_keys}
        missing_keys = [key for key, value in values.items() if not value]
        if missing_keys:
            raise ValueError(
                "Eksik ortam degiskenleri: " + ", ".join(sorted(missing_keys))
            )

        placeholder_keys = [
            key
            for key, value in values.items()
            if value.lower().startswith("senin_") or "buraya_yaz" in value.lower()
        ]
        if placeholder_keys:
            raise ValueError(
                "Bu anahtarlar hala ornek deger icermekte: "
                + ", ".join(sorted(placeholder_keys))
            )

        return cls(
            news_api_key=values["NEWS_API_KEY"],
            grok_api_key=values["GROK_API_KEY"],
            x_api_key=values["X_API_KEY"],
            x_api_secret=values["X_API_SECRET"],
            x_access_token=values["X_ACCESS_TOKEN"],
            x_access_secret=values["X_ACCESS_SECRET"],
            news_sources=os.getenv("NEWS_SOURCES", NEWS_SOURCES),
            grok_model=os.getenv("GROK_MODEL", GROK_MODEL),
        )


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def build_retry_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class PostedURLStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path

    def load(self) -> set[str]:
        if not self.file_path.exists():
            return set()

        with self.file_path.open("r", encoding="utf-8") as file:
            return {line.strip() for line in file if line.strip()}

    def add(self, url: str) -> None:
        with self.file_path.open("a", encoding="utf-8") as file:
            file.write(f"{url}\n")


class NewsAPIClient:
    def __init__(self, api_key: str, sources: str, session: requests.Session) -> None:
        self.api_key = api_key
        self.sources = sources
        self.session = session

    def fetch_top_headlines(self) -> list[Article]:
        params = {
            "sources": self.sources,
            "apiKey": self.api_key,
            "pageSize": 10,
        }

        try:
            response = self.session.get(
                NEWS_API_URL,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise RuntimeError("NewsAPI istegi basarisiz oldu.") from exc
        except ValueError as exc:
            raise RuntimeError("NewsAPI gecerli JSON donmedi.") from exc

        if payload.get("status") != "ok":
            raise RuntimeError(
                "NewsAPI hata dondu: "
                f"{payload.get('code', 'unknown')} - {payload.get('message', 'Mesaj yok')}"
            )

        articles: list[Article] = []
        for item in payload.get("articles", []):
            title = (item.get("title") or "").strip()
            description = (item.get("description") or "").strip()
            url = (item.get("url") or "").strip()

            if not title or not url:
                continue

            articles.append(
                Article(
                    title=title,
                    description=description,
                    url=url,
                )
            )

        return articles


class GrokClient:
    def __init__(self, api_key: str, model: str, session: requests.Session) -> None:
        self.api_key = api_key
        self.model = model
        self.session = session

    def summarize_article(self, article: Article) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": GROK_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Baslik: {article.title}\n"
                        f"Aciklama: {article.description or 'Aciklama bulunamadi.'}\n"
                        f"Baglanti: {article.url}"
                    ),
                },
            ],
            "temperature": 0.4,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self.session.post(
                GROK_API_URL,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            response_payload = response.json()
        except requests.RequestException as exc:
            raise RuntimeError("Grok API istegi basarisiz oldu.") from exc
        except ValueError as exc:
            raise RuntimeError("Grok API gecerli JSON donmedi.") from exc

        try:
            message = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Grok API yaniti beklenen formatta degil.") from exc

        summary = self._extract_text(message).strip()
        if not summary:
            raise RuntimeError("Grok API bos bir ozet dondurdu.")

        return collapse_whitespace(summary)

    @staticmethod
    def _extract_text(content: str | list[dict]) -> str:
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            return " ".join(parts)

        return ""


class XClient:
    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        access_secret: str,
    ) -> None:
        self.client = tweepy.Client(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_token=access_token,
            access_token_secret=access_secret,
            wait_on_rate_limit=True,
        )

    def post_tweet(self, text: str) -> str:
        try:
            response = self.client.create_tweet(text=text, user_auth=True)
        except tweepy.TweepyException as exc:
            raise RuntimeError("X uzerine tweet gonderilemedi.") from exc

        tweet_data = response.data or {}
        tweet_id = str(tweet_data.get("id", "")).strip()
        if not tweet_id:
            raise RuntimeError("X API tweet ID donmedi.")

        return tweet_id


class NewsBot:
    def __init__(
        self,
        news_client: NewsAPIClient,
        grok_client: GrokClient,
        x_client: XClient,
        url_store: PostedURLStore,
    ) -> None:
        self.news_client = news_client
        self.grok_client = grok_client
        self.x_client = x_client
        self.url_store = url_store

    def run_once(self) -> bool:
        posted_urls = self.url_store.load()
        logger.info("Kayitli %s URL bulundu.", len(posted_urls))

        articles = self.news_client.fetch_top_headlines()
        logger.info("NewsAPI toplam %s haber dondurdu.", len(articles))

        for article in self._iter_unposted_articles(articles, posted_urls):
            try:
                logger.info("Yeni haber isleniyor: %s", article.title)
                summary = self.grok_client.summarize_article(article)
                tweet_text = build_tweet_text(summary, article.url)
                tweet_id = self.x_client.post_tweet(tweet_text)
                self.url_store.add(article.url)
                logger.info("Tweet gonderildi. Tweet ID: %s", tweet_id)
                return True
            except Exception:
                logger.exception("Haber islenirken hata olustu: %s", article.url)

        logger.info("Paylasilacak yeni haber bulunamadi.")
        return False

    def run_forever(self) -> None:
        logger.info(
            "Bot baslatiliyor. Kontrol araligi: her %s saat.",
            CHECK_INTERVAL_HOURS,
        )
        self._run_cycle()
        schedule.every(CHECK_INTERVAL_HOURS).hours.do(self._run_cycle)

        while True:
            schedule.run_pending()
            time.sleep(30)

    def _run_cycle(self) -> None:
        logger.info("Yeni kontrol dongusu basladi.")
        try:
            self.run_once()
        except Exception:
            logger.exception("Kontrol dongusu genel hatayla sonlandi.")

    @staticmethod
    def _iter_unposted_articles(
        articles: Iterable[Article], posted_urls: set[str]
    ) -> Iterable[Article]:
        for article in articles:
            if article.url in posted_urls:
                logger.info("Daha once paylasildigi icin atlandi: %s", article.url)
                continue
            yield article


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def truncate_text(text: str, limit: int) -> str:
    clean_text = collapse_whitespace(text)
    if limit <= 0:
        return ""
    if len(clean_text) <= limit:
        return clean_text
    if limit <= 3:
        return clean_text[:limit]

    return clean_text[: limit - 3].rstrip() + "..."


def estimate_x_post_length(summary: str, url: str) -> int:
    normalized_summary = collapse_whitespace(summary)
    separator_length = 1 if normalized_summary and url else 0
    url_length = X_SHORT_URL_LENGTH if url else 0
    return len(normalized_summary) + separator_length + url_length


def build_tweet_text(summary: str, url: str) -> str:
    normalized_summary = collapse_whitespace(summary)

    while estimate_x_post_length(normalized_summary, url) > MAX_TWEET_LENGTH:
        summary_budget = MAX_TWEET_LENGTH - X_SHORT_URL_LENGTH - 1
        normalized_summary = truncate_text(normalized_summary, summary_budget - 1)

    return f"{normalized_summary} {url}".strip()


def build_bot(config: Config) -> NewsBot:
    news_session = build_retry_session()
    grok_session = build_retry_session()

    news_client = NewsAPIClient(
        api_key=config.news_api_key,
        sources=config.news_sources,
        session=news_session,
    )
    grok_client = GrokClient(
        api_key=config.grok_api_key,
        model=config.grok_model,
        session=grok_session,
    )
    x_client = XClient(
        consumer_key=config.x_api_key,
        consumer_secret=config.x_api_secret,
        access_token=config.x_access_token,
        access_secret=config.x_access_secret,
    )
    url_store = PostedURLStore(POSTED_URLS_PATH)
    return NewsBot(news_client, grok_client, x_client, url_store)


def main() -> None:
    configure_logging()

    try:
        config = Config.from_env()
        bot = build_bot(config)
        bot.run_forever()
    except KeyboardInterrupt:
        logger.info("Bot kullanici tarafindan durduruldu.")
    except Exception:
        logger.exception("Bot baslatilamadi.")


if __name__ == "__main__":
    main()
