# X (Twitter) Haber Botu

Bu proje, `bbc-news` ve `reuters` kaynaklarindan haber cekip Grok ile Turkce ozetleyen ve sonucu X uzerinde paylaşan Python tabanli bir bottur.

## Kurulum

```bash
python -m pip install -r requirements.txt
```

## Yapilandirma

1. `.env` dosyasindaki degiskenleri doldurun.
2. `GROK_API_KEY` su an ornek deger icermektedir; gercek xAI anahtarinizla degistirin.
3. Isterseniz `GROK_MODEL` degerini degistirerek farkli bir Grok modeli kullanabilirsiniz. Varsayilan deger `grok-beta` olarak birakildi.

## Calistirma

```bash
python news_bot.py
```

Bot baslarken bir kez calisir, sonra her 2 saatte bir yeni haber kontrolu yapar. Paylasilan URL'ler `posted_urls.txt` dosyasinda tutulur.
