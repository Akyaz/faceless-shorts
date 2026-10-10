# faceless-shorts

Türkçe gündem Shorts'larını ücretsiz araçlarla otomatik üreten pipeline.

Akış: Google News Türkiye RSS → metin → Edge TTS seslendirme → Pillow + ffmpeg ile altyazılı 1080x1920 video.

- `GEMINI_API_KEY` secret'ı tanımlıysa en üstteki haberden özgün bir hikaye metni yazılır.
- Tanımlı değilse "Günün 3 Haberi" özet formatı kullanılır (dil modeli gerekmez).
- Arka plan: her paragrafta Wikimedia Commons'tan serbest lisanslı ayrı bir fotoğraf (Gemini adayların fotoğrafına bakıp habere uymayanları eler), bulunamazsa Gemini illüstrasyonu, o da olmazsa renkli degrade. Görsel kaynakları açıklamaya yazılır.
- Fon müziği: haberin duygusuna göre (nötr, gergin, umutlu, hüzünlü) `assets/music` altındaki dört parçadan biri seslendirmenin altına hafifçe eklenir. Parçalar Kevin MacLeod (incompetech.com), CC BY 3.0; kaynak açıklamaya yazılır. Ses düzeyi `pipeline/music.py` içindeki `GAIN_DB` ile ayarlanır.

Çalıştırma: Actions sekmesinde **Short üret** → *Run workflow*. Video, çalışmanın "Artifacts" bölümünden indirilir.

Yerelde ağsız deneme: `python -m pipeline.main --offline`

YouTube yükleme kurulumu: [KURULUM.md](KURULUM.md)
