# faceless-shorts — çalışma kuralları

Haber ve gündem kanalı (YouTube Shorts, Instagram Reels) için otomatik video hattı: Türkçe gündem, spor, kültür,
dizi ve bilgi videoları; İngilizce türler de var, hedef küresel izlenmeyi de artırmak. Videolar GitHub Actions'ta
üretilir, metin ve görsel seçimi Gemini ile yapılır. Kanalın sahibi Akyaz. Yönetim paneli ayrı bir depoda
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
  Deneme videosu panelde "Önizle" ile izlenir (14 gün) ve sonradan panelden yüklenebilir. Bu yüzden deneme de gerçek bir video gibi kurallara uymalı.
- Videoyu silmek, gizlemek ya da yayından kaldırmak kullanıcının işi; önerilir, yapılmaz.
- GitHub secret'larını yazmak, iş akışlarını açıp kapatmak ve çalışma iptal etmek izinli değil. Gerekirse komutu
  kullanıcıya ver (örnek: `gh secret set TMDB_API_KEY`). Anahtar ve token isteme, tekrar yazma.
- `git push` öncesi `git pull --rebase`: başka oturumlar ve panel aynı dala yazıyor.

## Yedi ilke

Amaç paylaşım: izleyici videoyu birine göndermek istemeli. Kurallar bu yedi ilkenin uygulamasıdır.

| İlke | Kodda nerede |
|---|---|
| 1. **Konu:** insanların aradığı ya da konuştuğu tek bir güncel konu; olayda yer alan kişiler | `trends.py`, `script.STORIES` (seçim), `SUBJECTS_FIELD`, `slots.SLOTS` |
| 2. **İlk 2 saniye:** konunun görüntüsü ve haberin kendisi, ilk cümle en fazla 8 kelime, soru ya da giriş yok | `script.STORY_RULES`, `style_problems` |
| 3. **Görüntü:** yalnızca konunun gerçek görüntüsü, en az iki farklı kare; yoksa bilgi kartı; o da yoksa video yok | `main.subject_kind`, `main.settle_scenes`, `images.py` |
| 4. **Doğruluk:** her bilgi kaynakta var, tarih doğru, adı söylenmeyen "ünlü isim" yok, karttaki her sayı metinde | `script.text_problems`, `review.py`, `scenes.check` |
| 5. **Kısalık:** 55–75 kelime, 3–4 paragraf; ekranda az yazı (başlık yalnızca ilk 3 saniye) | `script.style_problems`, `render.HOOK_SECONDS` |
| 6. **Kapanış:** somut bir bilgi; soru yalnızca adı konmuş iki seçenek varsa; yorum çağrısı ve dolgu yok | `script.CLOSING_RULE`, `text_problems` |
| 7. **Az ama güçlü:** bu şartları tutturamayan video üretilmez, o saat boş geçer | `TextRejected`, `settle_scenes`, `with_subject_photos` |

Görsel kararı konuya göre verilir, video türüne göre değil (`subject_kind`): dizi ve film → yalnızca yapımın kareleri;
kişi → kişinin kendi fotoğrafları ve olayın geçtiği şehir; yer ve olay → o yerin fotoğrafı; yeri olmayan haber (burs,
zam) → bilgi kartları. Beğenilen örnek: Kızılcık Şerbeti videosu (15 Kasım 2026).

**Değişiklik kuralı:** Bir hata çıkınca önce hangi ilkenin tutmadığı bulunur ve o ilkenin tek uygulaması düzeltilir.
Yeni kural ancak eskisi kaldırılarak ya da birleştirilerek eklenir. Tür silmek ya da kapatmak için kanal sahibine sorulur.

## Kanal sahibinin kararları

- **Telif:** Dizi ve film haberinde yapımın resmi kareleri, afişi ve set fotoğrafı (12 Kasım 2026); serbest lisanslı
  fotoğrafı olmayan kişide kurumun resmi arşiv ya da basın fotoğrafı (`scripts/evergreen/images.json`, 14 Kasım
  2026). Hak sahibi açıklamaya yazılır. Ajans ve haber sitesi fotoğrafı, aile ve çocuk fotoğrafı kullanılmaz.
- **Ücretsiz:** Ücretli servis yok (TMDB, X API, Runway). Google Trends ücretsiz RSS'tir.
- **Kullanılmayan görseller:** kanal ve medya binaları, televizyon stüdyosu, büst ve heykel, "temsili" stok, eski ya
  da başka olaya ait görüntü. 29 Ekim'de Anıtkabir yok (10 Kasım içindir); Atatürk anılarında yalnızca belgeli olanlar.
- **Alınmayan konular:** NASCAR, Amishler, Amerikan tarihi, poker, işkence tarihi, kadın suçlular, mahkeme davaları,
  komplo teorileri, dini hikâyeler; borsa ve yatırım tavsiyesi; yaşlılara sağlık tavsiyesi; magazinde söylenti ve
  özel hayat. Para serisinde yalnızca kesinleşmiş skandallar. Can kaybı olan haberde soru, merak kancası ve abone
  çağrısı yok.
- **Takvim:** `pipeline/slots.py` `SLOTS`; saat değişirse panelin planı da (`faceless-shorts-panel/api.js`, `PLAN`).
  Uzun tarih videosu her gün 20:00'de (17 Kasım 2026); haftalık derleme takvimden çıktı, elle çalışır (15 Kasım 2026 ölçümü).
- Yabancı isimler Türkçe seslendirmede doğru okunur (`pronounce`). Son ~10 günde kullanılan görsel tekrar seçilmez.

## Geliştirme

- Testler: `python -m unittest discover -s tests`. Sistem Python'unda `ephem` yoksa sanal ortam kullan.
- Yeni davranışa test eklenir; ağa çıkan kod testte taklit edilir (`unittest.mock`).
- Değişiklikten sonra ilgili türde yüklemesiz deneme yapılır ve çıktı gözle kontrol edilir: metin, görseller ve
  kaynaklar. Adımlar `deneme-uretimi` skill'inde.
- GitHub API saatlik sınırı paylaşımlı. Çalışma beklerken `gh` döngüsü en az 2–4 dakika aralıkla sorgular.
