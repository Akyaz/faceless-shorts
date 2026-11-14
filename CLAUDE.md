# faceless-shorts — çalışma kuralları

Türkçe YouTube Shorts ve Instagram Reels kanalı için otomatik video hattı. Videolar GitHub Actions'ta üretilir.
Metin ve görsel seçimi Gemini ile yapılır. Kanalın sahibi Akyaz. Yönetim paneli ayrı bir depoda
(`../faceless-shorts-panel`). Ayrıntılar: [README.md](README.md), kurulum: [KURULUM.md](KURULUM.md).

## İletişim

- Kullanıcıya her yanıt **Türkçe**: ara notlar, özetler, raporlar. Araç çıktısı ya da bildirim İngilizce olsa da.
- Kod yorumları, commit mesajları, README ve iş akışı açıklamaları da Türkçe.
- Kod yorumu kararın nedenini ve tarihini söyler (örnek: "Gündem haberi en zayıf saatti (12 Kasım ölçümü)").

## Yayın güvenliği

- **Yüklemeden önce kontrol et.** Kullanıcı panelden aynı videoyu yüklemiş olabilir. Panelin tetiklediği iş de
  Actions'ta "Akyaz" olarak görünür, benim tetiklediğimle karışır. Bir videoyu YouTube'a ya da Instagram'a
  (yeniden) yüklemeden önce `panel-data` dalındaki `feed.json`'da o çalışmanın bağlantısına bak. Son dakikalarda
  aynı `run_id` için `upload-video` ya da `instagram` çalışması başlamış mı, ona da bak.
- Denemeler **yüklemesiz** yapılır: `gh workflow run make-short.yml -f mode=<tür> -f upload=false`.
  Deneme videosu sonradan panelden yüklenebilir. Bu yüzden deneme de gerçek bir video gibi kurallara uymalı.
- Videoyu silmek, gizlemek ya da yayından kaldırmak kullanıcının işi; önerilir, yapılmaz.
- GitHub secret'larını yazmak, iş akışlarını açıp kapatmak ve çalışma iptal etmek izinli değil. Gerekirse komutu
  kullanıcıya ver (örnek: `gh secret set TMDB_API_KEY`). Anahtar ve token isteme, tekrar yazma.
- `git push` öncesi `git pull --rebase`: başka oturumlar ve panel aynı dala yazıyor.

## Metin kuralları

- İlk cümle haberin kendisi. En fazla 8 kelime. Soru ya da retorik giriş yok.
- 55–75 kelime, 3–4 paragraf, sade ve betimleyen dil. Ayrıntılar önem sırasıyla verilir.
- Son cümle somut bir bilgidir. Genel soru yasak: "Sence bu karar ne anlama geliyor?", "Sen ne düşünüyorsun?"
  türü sorular kullanılmaz. Soru yalnızca adı konmuş iki seçenek varsa sorulur ("Fenerbahçe mi, Galatasaray mı?").
  Olayın doğal ve zorunlu sonucu tartışmaya açılmaz (selden sonra okulların tatil edilmesi gibi).
- **Belirsizlik yok.** Başlık ya da metin merak uyandırıyorsa cevap videoda ve açıklamada açıkça verilir.
  Kimin, neyin söz konusu olduğunu söylemeyen ifade ("ünlü isim", "o sahne") yasak.
- Can kaybı olan haberde merak kancası, soru ve abone çağrısı yok; haberin duygusuna uygun sade dil.
- "Bu senin için ne demek?" türü açıklama yok.
- Yabancı isimler Türkçe seslendirmede doğru okunur (`pronounce` alanı).
- Kodda karşılığı: `script.STORY_RULES`, `script.style_problems`, `script.vague`, `pipeline/review.py`.

## Görsel kuralları

- **Eski ya da başka olaya ait video ve görsel yok.** "Temsili" stok içerik önerme.
- Görsel haberin ülkesinden, haber bir şehirdeyse o şehirden.
- Yalnızca şehir adıyla arama yapılmaz: "Istanbul" araması her seferinde aynı Ataşehir manzarasını getiriyordu.
- Kanal ve medya şirketi binaları kullanılmaz (Kanal D genel merkezi). Kanal ve platform adı konu (`subjects`)
  olarak yazılmaz.
- Dizi ve film haberi: yapımın kendi kareleri. Resmi sahne görselleri, afiş ve set fotoğrafı kullanılır. Bunlar
  telifli; kanal sahibi kabul etti (12 Kasım 2026), hak sahibi açıklamaya yazılır.
  - Kaynak sırası: TMDB (`TMDB_API_KEY` varsa), haber kapakları (Gemini eler), Vikipedi afişi.
  - Yazılı haber kapağı, kolaj ve başka yapımın karesi kullanılmaz.
- Haber sitelerinin ve ajansların fotoğrafları telifli; dizi ve film dışında kullanılmaz.
- Maç gibi tek bir güne ait olayda başka tarihten portre yetmez. O güne ait kendi grafiklerimiz (skor, gol dakikası,
  kadro kartı) tercih edilir.
- Son ~10 günde kullanılan arama görseli tekrar seçilmez (`state/images.json`).
- 29 Ekim videolarında Anıtkabir görseli yok (Anıtkabir 10 Kasım içindir). Atatürk anılarında yalnızca belgeli olanlar.
- Az ama doğru görsel, çok ama alakasız görselden iyidir. Kural mümkünse kodla zorlanır, modele bırakılmaz.
- Bilgi videosunda en fazla iki paragraf animasyonlu sahne olur: sayaç, karşılaştırma, zaman çizelgesi ya da
  harita (`pipeline/scenes.py`). Sahnedeki her sayı paragrafta aynen geçer, harita koordinatı Vikipedi'den gelir.

## İçerik seçimi

- Az ama güçlü video: zayıf videolar kanalın bütün videolarının gösterimini düşürüyor.
- Amaç paylaşım ve yeni kitleye görünürlük: izleyici videoyu birine göndermek istemeli.
- Alınmayan nişler: NASCAR, Amishler, Amerikan tarihi, poker, işkence tarihi, kadın suçlular, mahkeme davaları,
  komplo teorileri, dini hikâyeler. Ayrıca borsa ve yatırım tavsiyesi ile yaşlılara sağlık tavsiyesi verilmez.
- Magazinde söylenti ve özel hayat yok. Para serisinde yalnızca kesinleşmiş skandallar anlatılır.
- Zamanlama ve saat-tür eşleşmesi `pipeline/slots.py` içindeki `SLOTS` tablosunda. Saat değişirse panelin günlük
  planı da güncellenir (`faceless-shorts-panel/api.js`, `PLAN`).

## Geliştirme

- Testler: `python -m unittest discover -s tests`. Sistem Python'unda `ephem` yoksa sanal ortam kullan.
- Yeni davranışa test eklenir; ağa çıkan kod testte taklit edilir (`unittest.mock`).
- Değişiklikten sonra ilgili türde yüklemesiz deneme yapılır ve çıktı gözle kontrol edilir: metin, görseller ve
  kaynaklar. Adımlar `deneme-uretimi` skill'inde.
- GitHub API saatlik sınırı paylaşımlı. Çalışma beklerken `gh` döngüsü en az 2–4 dakika aralıkla sorgular.
