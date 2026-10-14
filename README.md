# faceless-shorts

Türkçe gündem Shorts'larını ücretsiz araçlarla otomatik üreten pipeline.

Akış: Google News Türkiye RSS → metin → Edge TTS seslendirme → Pillow + ffmpeg ile altyazılı 1080x1920 video.

- `GEMINI_API_KEY` secret'ı tanımlıysa en üstteki haberden özgün bir hikaye metni yazılır.
- Tanımlı değilse "Günün 3 Haberi" özet formatı kullanılır (dil modeli gerekmez).
- Arka plan: her paragrafta Wikimedia Commons'tan serbest lisanslı ayrı bir fotoğraf (Gemini adayların fotoğrafına bakıp habere uymayanları eler), bulunamazsa Gemini illüstrasyonu, o da olmazsa renkli degrade. Görsel kaynakları açıklamaya yazılır.
- Fon müziği: haberin duygusuna göre (nötr, gergin, umutlu, hüzünlü) `assets/music` altındaki dört parçadan biri seslendirmenin altına hafifçe eklenir. Parçalar Kevin MacLeod (incompetech.com), CC BY 3.0; kaynak açıklamaya yazılır. Ses düzeyi `pipeline/music.py` içindeki `GAIN_DB` ile ayarlanır.

Kendi metninle video: `scripts/custom/` altındaki JSON dosyası iş akışının `script` girdisine verilir ya da aynı içerik `script_json` girdisiyle doğrudan gönderilir (yönetim panelinin Metin ekranı bunu yapar). Alanlar için örnek: `scripts/custom/2026-10-14-en.json`.

Video türleri (`--mode`): `story` tek bir gündem haberini anlatır, `world` dünya gündeminden tek bir haberi tamamen İngilizce anlatır (metin, ekran yazıları, başlık ve açıklama), `trend` bilim ve teknolojiden merak uyandıran 4 gelişmeyi özetler, `digest` günün öne çıkan 5 haberini, `sports` spor gündeminden 4 başlığı özetler.

Zamanlama (Türkiye saati, günde 9 video): 07:15 sabah özeti; 10:00, 12:00, 17:00 ve 19:00'da birer gündem haberi; 13:30 spor gündemi; 15:00 trend; 16:00 İngilizce dünya haberi; 20:30 günün özeti. YouTube kanala günde yaklaşık 10 yüklemeye izin verdiği için sayı bununla sınırlı. GitHub zamanlanmış işleri geciktirebilir ya da atlayabilir.

Maç programı: `python -m pipeline.fixtures` (iş akışında `ucl` türü) Şampiyonlar Ligi'nde o günün maçlarını ve Türkiye saatiyle başlama saatlerini tek bir tabloda gösteren 12 saniyelik bir video üretir; o gün maç yoksa video çıkmaz. `--results` (iş akışında "results") önce bir önceki günün sonuçlarını skorlar tek tek gelecek şekilde gösterir; `--emphasize` seçilen takımların maçını kırmızı çerçeveye alır. Veri ESPN'in açık skor tablosundan alınır.

Haftalık derleme: **Haftalık derleme** iş akışı her pazar 11:00'de son 7 günün tek haber videolarından 10 haber seçip yatay (1920x1080), yaklaşık 5 dakikalık bir video üretir (`pipeline/weekly.py`). Metinler yeniden yazılmaz; "yarın", "bugün" gibi o güne bağlı ifade içeren haberler alınmaz.

Çalıştırma: Actions sekmesinde **Short üret** → *Run workflow*. Video, çalışmanın "Artifacts" bölümünden indirilir.

Yerelde ağsız deneme: `python -m pipeline.main --offline`

YouTube yükleme kurulumu: [KURULUM.md](KURULUM.md)
