# X news bot

NewsAPI kaynaklarından haber alan, yapılandırılmış bir Grok modeliyle Türkçe özet oluşturan ve onaylı X hesabına gönderen küçük bir polling pipeline'ı.

Akış:

```text
NewsAPI → URL canonicalization/SQLite → Grok summary → length guard → X API
```

## Güvenlik ve davranış

- API anahtarları yalnızca ortam değişkenlerinden okunur; `.env` commit edilmez.
- `GROK_MODEL` zorunlu config alanıdır; model adı kaynak koda gömülü değildir.
- `--dry-run` X kimlik bilgisi istemeden özet/tweet önizlemesi üretir ve paylaşım yapmaz.
- Paylaşılan, başarısız ve dry-run haberler SQLite'ta durum/attempt bilgisiyle tutulur.
- URL'ler `utm_*`, `gclid`, `fbclid` ve fragment temizlenerek canonical biçimde deduplicate edilir.
- NewsAPI/Grok HTTP isteklerinde timeout, Retry-After uyumu, exponential backoff ve 429/5xx retry vardır.
- Grok ve X çağrılarında yapılandırılabilir minimum aralık uygulanır; Tweepy ayrıca X rate limitini bekler.
- Loglar JSON satırlarıdır. Anahtarlar, authorization header veya ham API response body loglanmaz.

## Kurulum

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env
```

`.env` içindeki placeholder değerlerini gerçek secret/config değerleriyle değiştirin. Anahtarları issue, log veya komut satırına yapıştırmayın.

## Güvenli ilk çalıştırma

Tek polling cycle, X'e göndermeden:

```bash
python news_bot.py --dry-run
```

Tek gerçek cycle:

```bash
python news_bot.py --once
```

Sürekli çalışma:

```bash
python news_bot.py
```

Varsayılan aralık 2 saattir ve `CHECK_INTERVAL_HOURS` ile değiştirilir.

## SQLite state

Varsayılan veritabanı `data/news_bot.db` yolundadır. `articles` tablosu canonical/original URL, başlık, status, attempt sayısı, son hata, tweet ID ve timestamp alanlarını tutar.

Eski `posted_urls.txt` varsa açılışta idempotent biçimde `posted` kayıtlarına taşınır; dosya otomatik silinmez. Başarısız bir makale `MAX_ARTICLE_ATTEMPTS` sınırına kadar sonraki cycle'larda yeniden denenir.

## Yapılandırma

| Değişken | Zorunlu | Varsayılan |
| --- | --- | --- |
| `NEWS_API_KEY` | Evet | — |
| `GROK_API_KEY` | Evet | — |
| `GROK_MODEL` | Evet | — |
| `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET` | Gerçek post için | — |
| `NEWS_SOURCES` | Hayır | `bbc-news,reuters` |
| `CHECK_INTERVAL_HOURS` | Hayır | `2` |
| `REQUEST_TIMEOUT_SECONDS` | Hayır | `30` |
| `GROK_MIN_INTERVAL_SECONDS` | Hayır | `1` |
| `X_MIN_INTERVAL_SECONDS` | Hayır | `1` |
| `MAX_ARTICLE_ATTEMPTS` | Hayır | `5` |
| `BOT_DB_PATH` | Hayır | `data/news_bot.db` |

## Test

Storage/dedup regresyon testleri harici API çağrısı yapmaz:

```bash
python -m unittest discover -s tests -v
```

## Çevrimdışı haber kalitesi raporu

Kaydedilmiş NewsAPI JSON yanıtını API anahtarı kullanmadan veya paylaşım yapmadan denetleyin:

```bash
python headline_audit.py response.json --json
```

`missing_descriptions` alanı açıklaması eksik, boş veya yalnızca boşluk içeren
makaleleri sayar. Başlık/URL geçerliyse makale hâlâ `usable` sayılır; `--strict`
bu bilgilendirici metriği tek başına hata kabul etmez. Rapor başlıkları,
açıklamaları veya URL'leri içermez.

## Sınırlamalar

- Kaynak başlık/açıklaması hatalıysa özet de hatalı olabilir.
- Otomatik paylaşım editoryal doğrulamanın yerini tutmaz.
- URL canonicalization farklı içerik sunan bazı query parametrelerini korur; yalnızca bilinen tracking parametreleri atılır.
- X/NewsAPI/xAI kullanım şartları ve ücretleri deploy öncesi ayrıca kontrol edilmelidir.

