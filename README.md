# faceless-shorts

Türkçe gündem Shorts'larını ücretsiz araçlarla otomatik üreten pipeline.

Akış: Google News Türkiye RSS → metin → Edge TTS seslendirme → Pillow + ffmpeg ile altyazılı 1080x1920 video.

- `GEMINI_API_KEY` secret'ı tanımlıysa en üstteki haberden özgün bir hikaye metni yazılır.
- Tanımlı değilse "Günün 3 Haberi" özet formatı kullanılır (dil modeli gerekmez).
- Arka plan: her paragrafta Wikimedia Commons'tan serbest lisanslı ayrı bir fotoğraf (Gemini adayların fotoğrafına bakıp habere uymayanları eler), bulunamazsa Gemini illüstrasyonu, o da olmazsa renkli degrade. Görsel kaynakları açıklamaya yazılır.
- Fon müziği: haberin duygusuna göre (nötr, gergin, umutlu, hüzünlü) `assets/music` altındaki dört parçadan biri seslendirmenin altına hafifçe eklenir. Parçalar Kevin MacLeod (incompetech.com), CC BY 3.0; kaynak açıklamaya yazılır. Ses düzeyi `pipeline/music.py` içindeki `GAIN_DB` ile ayarlanır.

Video türleri (`--mode`): `story` tek bir haberi anlatır, `digest` günün öne çıkan 5 haberini, `sports` spor gündeminden 4 başlığı özetler.

Zamanlama (Türkiye saati): 07:15'te 3 tek haber videosu; 10:00, 12:00, 15:00, 17:00, 19:00 ve 23:00'te birer tek haber; 13:30'da spor gündemi; 20:30'da günün özeti. GitHub zamanlanmış işleri geciktirebilir ya da atlayabilir.

Haftalık derleme: **Haftalık derleme** iş akışı her pazar 11:00'de son 7 günün tek haber videolarından 10 haber seçip yatay (1920x1080), yaklaşık 5 dakikalık bir video üretir (`pipeline/weekly.py`). Metinler yeniden yazılmaz; "yarın", "bugün" gibi o güne bağlı ifade içeren haberler alınmaz.

Çalıştırma: Actions sekmesinde **Short üret** → *Run workflow*. Video, çalışmanın "Artifacts" bölümünden indirilir.

Yerelde ağsız deneme: `python -m pipeline.main --offline`

YouTube yükleme kurulumu: [KURULUM.md](KURULUM.md)
