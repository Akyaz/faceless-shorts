# YouTube otomatik yükleme kurulumu

Bir kerelik yapılır, yaklaşık 15 dakika sürer. Sonunda GitHub'a 3 secret eklenir.

## 1. Google Cloud projesi
1. https://console.cloud.google.com adresine kanalın bağlı olduğu Google hesabıyla gir.
2. Üstteki proje seçiciden **New Project** → adı `faceless-shorts` → Create.
3. **APIs & Services → Library** → "YouTube Data API v3" ara → **Enable**.

## 2. İzin ekranı (OAuth consent screen)
1. **APIs & Services → OAuth consent screen** (yeni arayüzde "Google Auth Platform").
2. Uygulama adı: `faceless-shorts`, destek e-postası: kendi adresin. Kullanıcı türü: **External**.
3. **Audience** bölümünde kendi Google hesabını **Test users** listesine ekle.
4. Aynı bölümde **Publish app** ile durumu **In production** yap.
   Bunu yapmazsan Google, "Testing" durumundaki uygulamaların yetkisini 7 günde bir düşürür ve yükleme durur.
   Doğrulama başvurusu yapman gerekmez; kendi hesabınla kullanırken sadece bir uyarı ekranı görürsün.

## 3. İstemci kimliği
1. **Clients** (veya Credentials) → **Create client** → tür: **Desktop app** → Create.
2. Çıkan **Client ID** ve **Client secret** değerlerini bir kenara not et.

## 4. Refresh token (kendi bilgisayarında)
Depoyu indir ya da sadece `scripts/get_refresh_token.py` dosyasını kaydet, sonra Terminal'de:

```
python3 get_refresh_token.py CLIENT_ID CLIENT_SECRET
```

Tarayıcıda kanalın bağlı olduğu hesabı seç. "Google bu uygulamayı doğrulamadı" uyarısında
**Advanced → Go to faceless-shorts** de (uygulama senin). Kanal bir marka hesabıysa listeden kanalı seç.
Terminalde `YT_REFRESH_TOKEN` değeri yazacak.

## 5. GitHub secret'ları
Depoda **Settings → Secrets and variables → Actions → New repository secret** ile üçünü ekle:

| Ad | Değer |
| --- | --- |
| `YT_CLIENT_ID` | 3. adımdaki Client ID |
| `YT_CLIENT_SECRET` | 3. adımdaki Client secret |
| `YT_REFRESH_TOKEN` | 4. adımdaki token |

## Kullanım
- **Short üret** iş akışında "Üretilen videoyu kanala da yükle" kutusunu işaretle.
- Daha önce üretilmiş bir videoyu yüklemek için **Hazır videoyu yükle** iş akışına o çalışmanın numarasını gir.
