# Uzun videolar (tarih)

Her dosya 8-12 dakikalık bir yatay video. Metinler elle yazılır ve yazılmadan önce en az iki bağımsız kaynakla
karşılaştırılır; kaynaklar `sources` alanında bağlantılarıyla durur ve video açıklamasına yazılır.
Üretim: `python -m pipeline.longform scripts/longform/<dosya>.json` ya da **Tarih videosu** iş akışı.

`queue.txt` yayın sırasıdır: zamanlanmış çalışma her gün sıradaki yayınlanmamış dosyayı üretip yükler.

## Alanlar

| Alan | Açıklama |
| --- | --- |
| `lang` | `tr` ya da `en` |
| `topic`, `era`, `country` | Konu, dönem ve ülke (İngilizce); görsel seçiminde kullanılır |
| `label` | Ekrandaki etiket (TARİH, HISTORY) |
| `title`, `description`, `hashtags`, `tags` | YouTube başlığı, açıklamanın girişi, etiketler |
| `speakers` | İki konuşmacı: `{"A": {"name": "Elif", "voice": "female"}, "B": {...}}` |
| `sources` | `[{"title", "url"}]` |
| `chapters` | Bölümler: `heading`, isteğe bağlı `country` ve `city`, `image_queries` (İngilizce), isteğe bağlı `image_files` (elle seçilmiş Wikimedia dosyaları), `lines`: `[{"s": "A", "t": "..."}]` |

İlk bölüm diyalogla açılır (kanca); sonraki bölümlerin başında bölüm kartı gösterilir. Türkçe metin için
yaklaşık 1.100-1.400 kelime, İngilizce için 1.300-1.700 kelime 8-12 dakika eder.
