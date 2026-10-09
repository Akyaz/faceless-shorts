# faceless-shorts

Türkçe gündem Shorts'larını ücretsiz araçlarla otomatik üreten pipeline.

Akış: Google News Türkiye RSS → metin → Edge TTS seslendirme → Pillow + ffmpeg ile altyazılı 1080x1920 video.

- `GEMINI_API_KEY` secret'ı tanımlıysa en üstteki haberden özgün bir hikaye metni yazılır.
- Tanımlı değilse "Günün 3 Haberi" özet formatı kullanılır (dil modeli gerekmez).
- Arka plan: Wikimedia Commons'tan serbest lisanslı bir fotoğraf, bulunamazsa Gemini illüstrasyonu, o da olmazsa renkli degrade. Görsel kaynağı açıklamaya yazılır.

Çalıştırma: Actions sekmesinde **Short üret** → *Run workflow*. Video, çalışmanın "Artifacts" bölümünden indirilir.

Yerelde ağsız deneme: `python -m pipeline.main --offline`
