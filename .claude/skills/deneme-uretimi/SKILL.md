---
name: deneme-uretimi
description: faceless-shorts'ta yüklemesiz deneme videosu üretir ve kontrol eder. Metin, görsel ve kaynakları proje kurallarına göre denetler. Kod değişikliğinden sonra, "deneme yap", "bir video üret de bakalım", "görseller düzeldi mi", "şu türü test et" denince ya da bir video kanala yüklenmeden önce kullan.
---

# Deneme üretimi ve kontrol

Değişikliğin gerçek bir videoda nasıl göründüğünü yüklemeden görmek için. Kurallar `CLAUDE.md`'de. Bu skill
onları adım adım uygular.

## 1. Başlat

Değişiklik `main` dalına gönderilmiş olmalı: iş akışı depodaki kodu çalıştırır.

```bash
gh workflow run make-short.yml -f mode=<tür> -f upload=false
gh run list -w make-short.yml -L 3 --json databaseId,createdAt,event   # yeni çalışmanın numarası
```

Türler: `platform`, `fact`, `culture`, `sportstory`, `story`, `debate`, `matchday`, `world`, `trend`, `digest`,
`sports`, `horoscope1-3`. Birden çok tür denenecekse her biri ayrı çalışmadır.

**Asla `upload=true` ile deneme yapma.** Kullanıcı deneme videosunu beğenirse panelden ya da 4. adımla yüklenir.

## 2. Bekle ve topla

Arka planda çalıştır, bitince bildirim gelir. Döngüde `sleep` kullanılır, GitHub API sınırı yüzünden sık sorgulanmaz:

```bash
bash .claude/skills/deneme-uretimi/kontrol.sh <çalışma_no> [<çalışma_no> ...]
```

Betik her çalışma için şunları yazar:
- sonuç;
- günlükteki görsel ve hata satırları;
- başlık, metin, kelime sayısı, kaynaklar ve görsel kaynakları.

Videodan dört kareyi yan yana `kareler.jpg` olarak çıkarır ve dosya yolunu yazar.

Çalışma "slot" adımında uzun süre bekliyorsa öndeki bir çalışmayı bekliyordur (`pipeline/slots.py`,
`wait_for_running`). Sırada günlerce takılı kalan çalışma varsa kullanıcıdan iptal etmesini iste; iptal sende izinli değil.

## 3. Kontrol et

`kareler.jpg` dosyasını Read ile aç ve **gözle bak**. Günlük satırı görselin doğru olduğunu kanıtlamaz.

Metin:
- İlk cümle haberin kendisi mi, en fazla 8 kelime mi? Soru ya da retorik giriş var mı?
- 55–75 kelime, 3–4 paragraf mı? (Betik sayar.)
- Son cümle somut bir bilgi mi? Genel soru ("sence", "ne düşünüyorsun") var mı?
- Belirsiz ifade var mı ("ünlü isim", "o sahne")? Merak uyandıran her şeyin cevabı videoda mı?
- Bilgiler kaynaklarla uyumlu mu? Kaynakta olmayan rakam ya da iddia var mı?
- Can kaybı olan haberde soru ya da abone çağrısı var mı?

Görsel:
- Her kare konunun kendisini mi gösteriyor (kişi, yapım, yer, olay)?
- Genel şehir manzarası, kanal binası, başka ülke ya da başka olay görseli var mı?
- Dizi ve filmde yapımdan kare mi? Yazılı haber kapağı, kolaj ya da başka dizinin karesi var mı?
- Son günlerde çıkan videolarla aynı görsel mi? (`Son günlerde kullanılmış ... görsel atlandı` satırına bak.)
- Görsel kaynakları açıklamada eksiksiz mi?

Bir sorun bulursan nedenini günlükte bul: hangi arama, hangi aday, hangi seçim. Sonra kodu düzelt, test ekle,
gönder ve aynı türde yeniden dene.

## 4. Yüklemek gerekirse

Yalnızca kullanıcı isterse. Önce aynı videonun yüklenmediğini doğrula:

```bash
git fetch -q origin panel-data
git show origin/panel-data:feed.json | python3 -c "import json,sys; [print(e['run'], e.get('mode'), [(v.get('url'), v.get('instagram')) for v in e.get('videos', [])]) for e in json.load(sys.stdin)[-10:]]"
gh run list -w upload-video.yml -L 5
```

Ardından:

```bash
gh workflow run upload-video.yml -f run_id=<çalışma_no> -f privacy=public
```

Herkese açık dikey video bu iş akışında Instagram'a da otomatik gider (`instagram.yml`).

## 5. Raporla

Kullanıcıya Türkçe ve kısa yaz:
- hangi tür denendi ve konu ne;
- metin kurallara uyuyor mu (sorun varsa cümlesiyle);
- görseller ne gösteriyor;
- ne düzeltildi, neyin hâlâ beklendiği.

Kanala yüklenmediğini belirt.
