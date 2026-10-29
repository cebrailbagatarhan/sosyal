# NewsAPI başlık anlık görüntülerini karşılaştırma

İki **önceden kaydedilmiş** NewsAPI top-headlines JSON yanıtındaki URL
kesişimini çevrimdışı karşılaştırın. Ağ isteği, X paylaşımı veya bot
durumu değişikliği yapılmaz; API anahtarları okunmaz.

Kullanım:

    python headline_compare.py eski.json yeni.json
    python headline_compare.py eski.json yeni.json --json
    python -m unittest discover -s tests -p 'test_headline_compare.py' -v

Çıktı yalnız önceki ve güncel benzersiz geçerli URL sayıları, ortak/yeni/
çıkarılmış URL sayıları ve Jaccard benzerliğidir (0–1). Başlıklar, URL'ler
ve kaynak metinleri raporda gösterilmez. Aynı URL birden fazla görünse
bile bir kez sayılır. Geçersiz URL'ler atlanır. İki boş kümenin
benzerliği 1.0 kabul edilir. URL karşılaştırması tam dize eşitliğine
dayanır; tracking parametrelerini veya yönlendirmeleri normalleştirmez.

Her giriş en fazla 5 MB olabilir. Geçersiz dosya/yapı durumunda araç
hassas içerikleri yazdırmadan çıkış kodu 2 ile sonlanır.
