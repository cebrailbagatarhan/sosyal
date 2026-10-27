# Çevrimdışı NewsAPI başlık denetimi

Botu çalıştırmadan önce **daha önce dışa aktarılmış** bir NewsAPI `top-headlines`
JSON yanıtının yapısını denetleyebilirsiniz. Araç ağ isteği yapmaz, X'e paylaşım
göndermez ve `.env` veya API anahtarlarını okumaz.

Örnek `headlines.json` (gerçek anahtar veya kişisel veri eklemeyin):

```json
{
  "status": "ok",
  "articles": [
    {
      "title": "Örnek haber",
      "url": "https://example.com/news/1",
      "source": {"name": "Örnek Kaynak"}
    }
  ]
}
```

```bash
python headline_audit.py headlines.json
python headline_audit.py headlines.json --json
python headline_audit.py headlines.json --strict
python -m unittest discover -s tests -p 'test_headline_audit.py' -v
```

Rapor yalnız toplam kayıt, kullanılabilir kayıt, eksik başlık, geçersiz URL,
yinelenen URL, bozuk kayıt ve farklı kaynak **sayılarını** içerir; ham başlık
ve URL'leri yazdırmaz. `--strict` ile 0 sorunsuz, 1 veri kalitesi sorunu,
2 okunamayan/geçersiz giriş anlamına gelir. Giriş sınırı 5 MB'dir.

Bu denetim, haberin doğruluğunu veya tarafsızlığını değerlendirmez.
Açık PR #1'deki bot durum yönetimini ve PR #2'deki paylaşılmış URL
geçmişi raporunu değiştirmez.
