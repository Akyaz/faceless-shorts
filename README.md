# faceless-shorts

Türkçe gündem Shorts'larını ücretsiz araçlarla otomatik üreten pipeline.

Akış: Google News Türkiye RSS → metin → Edge TTS seslendirme → Pillow + ffmpeg ile altyazılı 1080x1920 video.

- `GEMINI_API_KEY` secret'ı tanımlıysa en üstteki haberden özgün bir hikaye metni yazılır.
- Tanımlı değilse "Günün 3 Haberi" özet formatı kullanılır (dil modeli gerekmez).
- Haftalık burç (`pipeline/horoscope.py`): pazartesi 08:00, 08:30 ve 09:00'da üç Shorts, her birinde dört burç. Haftanın gökyüzü olayları (gezegenlerin burç değiştirdiği günler, yeniay ve dolunay, geri hareket, Ay'ın günlere göre burcu) PyEphem ile hesaplanır, Gemini yorumu bu tarihlere dayandırır. Görsel her burcun Urania's Mirror (1824) kartı. Pazartesi maç programı çıkmaz.
- Metin denetimi (`pipeline/review.py`, `pipeline/articles.py`): yazılan metin yayından önce aynı haberin yayın sitelerindeki tam metniyle (Google News kümesindeki 2-3 site) karşılaştırılır. Metnin cevaplamadığı soru ("hangi 5 ilçe?", "neden men edildi?") ya da yanlış bilgi varsa bu metinlerden düzeltilir. Cevap metinlerde yoksa tek konulu videoda sıradaki haber denenir, özette o madde çıkarılır. Hiçbir sitenin metni okunamazsa ya da Gemini yanıt vermezse metin olduğu gibi kullanılır. `REVIEW=0` ortam değişkeniyle kapatılır.
- Arka plan: her paragrafta Wikimedia Commons'tan serbest lisanslı ayrı bir fotoğraf (Gemini adayların fotoğrafına bakıp habere uymayanları eler), bulunamazsa Gemini illüstrasyonu, o da olmazsa renkli degrade. Görsel kaynakları açıklamaya yazılır.
- Dijital platformlar (`pipeline/platforms.py`, `--mode platform`): Netflix'in resmi haftalık Türkiye Top 10 listesindeki yapımlar (her biri için Google News'te haber aranır) ve Netflix, Disney+, Prime Video, HBO Max, tabii ve Exxen'in yeni dizi ve film haberleri; haberin sitesindeki metnin başı da Gemini'ye verilir. Dizi ve film haberlerinde (`platform`, `culture`) yapımın resmi tanıtım görselleri kullanılır: `TMDB_API_KEY` secret'ı tanımlıysa TMDB'nin sahne görselleri ve afişi, değilse Vikipedi bilgi kutusundaki afiş. Bunlar telifli görsellerdir (kanal sahibinin kararı); hak sahibi açıklamaya yazılır.
- Fon müziği: haberin duygusuna göre (nötr, gergin, umutlu, hüzünlü) `assets/music` altındaki dört parçadan biri seslendirmenin altına hafifçe eklenir. Parçalar Kevin MacLeod (incompetech.com), CC BY 3.0; kaynak açıklamaya yazılır. Ses düzeyi `pipeline/music.py` içindeki `GAIN_DB` ile ayarlanır.

Kendi metninle video: `scripts/custom/` altındaki JSON dosyası iş akışının `script` girdisine verilir ya da aynı içerik `script_json` girdisiyle doğrudan gönderilir (yönetim panelinin Metin ekranı bunu yapar). Alanlar için örnek: `scripts/custom/2026-10-14-en.json`.

Video türleri (`--mode`): `story` tek bir gündem haberini anlatır, `world` dünya gündeminden tek bir haberi tamamen İngilizce anlatır (metin, ekran yazıları, başlık ve açıklama), `trend` bilim ve teknolojiden merak uyandıran 4 gelişmeyi özetler, `digest` günün öne çıkan 5 haberini, `sports` spor gündeminden 4 başlığı özetler. `fact` eskimeyen bir "Biliyor muydun?" konusunu anlatır: `scripts/evergreen/topics.txt` listesindeki sıradaki konunun Vikipedi sayfasından (Türkçe sayfa kısaysa İngilizcesinden) metin yazılır; işlenen konular `state/evergreen.json`'da tutulur. Listeye satır eklemek yeni konu eklemek için yeterli. Konular kategorilere ayrılır (`[otomobil]`, `[para]`, `[muhendislik]`, `[tarih]`; başlıksız olanlar "Biliyor muydun?"); her video sırası gelen kategoriden çıkar, ekran etiketi ve etiketler kategoriye göredir (`evergreen.CATEGORIES`).

Şablon çeşitliliği: her dikey video başlığından türetilen kendi görünümüyle çıkar (`render.make_style`): renk paleti, ekran başlığının rengi ve kutusu, altyazının boyutu, yeri, kelime sayısı, konuşulan kelimenin vurgusu, görüntünün hareketi, fotoğrafın karartması, anlatıcının sesi (kadın/erkek) ve hızı. Seçilen stil `metadata.json` içinde `plan.style` olarak durur; hangi stilin daha çok izlendiği buradan karşılaştırılabilir.

Zamanlama (Türkiye saati, günde 6 Shorts, maç günü 7, ve 1 tarih videosu): 10:00 dijital platformlar (Netflix Top 10, yeni dizi ve filmler); 12:00 ve 15:00'te eskimeyen bilgi serileri (Biliyor muydun?, otomobil ve motor, para ve iş, bilim ve mühendislik, tarih ve dünya, sırayla); 17:00 magazin ve kültür-sanat (`culture`: film, dizi, konser, tiyatro, ödül; söylenti ve özel hayat yok); 13:30 maç programı (Süper Lig maçı varsa Süper Lig, yoksa Türk takımlarının Avrupa maçları; maç yoksa video çıkmaz); 19:00 tek konulu spor haberi (`sportstory`: büyük kulüpler, derbi, transfer, Avrupa'daki Türk takımları; skor, karar ya da rakam ilk cümlede); 20:30 "Sen ne dersin?" tartışması; 21:00 sıradaki tarih videosu. Az ama güçlü video: çok sayıda zayıf video kanalın bütün videolarının gösterimini düşürüyor. GitHub zamanlanmış işleri geciktirebilir ya da atlayabilir.

Maç programı: `python -m pipeline.fixtures --auto` (iş akışında `matchday` türü) o gün Süper Lig maçı varsa Süper Lig programını, yoksa Türk takımlarının Şampiyonlar Ligi, Avrupa Ligi ve Konferans Ligi maçlarını gösterir; `--league ucl|uel|uecl|superlig` tek bir turnuvayı seçer. `python -m pipeline.fixtures` (iş akışında `ucl` türü) Şampiyonlar Ligi'nde o günün maçlarını ve Türkiye saatiyle başlama saatlerini tek bir tabloda gösteren 12 saniyelik bir video üretir; o gün maç yoksa video çıkmaz. `--results` (iş akışında "results") önce bir önceki günün sonuçlarını skorlar tek tek gelecek şekilde gösterir; `--emphasize` seçilen takımların maçını kırmızı çerçeveye alır. Veri ESPN'in açık skor tablosundan alınır.

Haftalık derleme: **Haftalık derleme** iş akışı her pazar 11:00'de son 7 günün tek haber videolarından 10 haber seçip yatay (1920x1080), yaklaşık 5 dakikalık bir video üretir (`pipeline/weekly.py`). Metinler yeniden yazılmaz; "yarın", "bugün" gibi o güne bağlı ifade içeren haberler alınmaz.

Çalıştırma: Actions sekmesinde **Short üret** → *Run workflow*. Video, çalışmanın "Artifacts" bölümünden indirilir.

Yerelde ağsız deneme: `python -m pipeline.main --offline`

YouTube yükleme kurulumu: [KURULUM.md](KURULUM.md)
