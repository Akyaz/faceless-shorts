"""Seri oynatma listeleri: her video türünün kendi listesi.

Liste, izleyiciye aynı türden sonraki videoyu önerir ve YouTube aramasında ayrıca görünür (14 Kasım 2026,
bulunabilirlik çalışması). Liste yoksa ilk yüklemede açılır (pipeline/upload.py); adı burada değişirse yeni liste açılır.
"""

PLAYLISTS = {
    "Netflix ve Dijital Platformlar": "Netflix Türkiye Top 10, yeni dizi ve filmler; Disney+, Prime Video, HBO Max, "
                                      "tabii ve Exxen'den haberler.",
    "Dizi, Film ve Kültür-Sanat": "Diziler, filmler, konserler, tiyatro ve ödüller: kültür-sanat dünyasından haberler.",
    "Biliyor muydun?": "Her gün bir ilginç bilgi: bilim, doğa, uzay ve dünyadan şaşırtan gerçekler.",
    "Otomobil ve Motor": "Otomobil ve motor dünyasının hikâyeleri: Devrim'den Togg'a, efsane modellerden motor "
                         "sporlarına.",
    "Para ve İş Dünyası": "Şirketlerin, girişimlerin ve paranın hikâyeleri. Yatırım tavsiyesi değildir.",
    "Bilim ve Mühendislik": "Köprüler, tüneller, uçaklar ve icatlar: büyük projelerin ve buluşların hikâyeleri.",
    "Tarih ve Dünya": "Antik medeniyetlerden yakın tarihe, dünyayı değiştiren olaylar ve yerler.",
    "Spor Haberleri": "Süper Lig, derbiler, transferler ve Avrupa'daki Türk takımları: günün spor haberi.",
    "Maç Programı": "Günün maçları ve sonuçları: Süper Lig ve Türk takımlarının Avrupa maçları, Türkiye saatiyle.",
    "Sen Ne Dersin?": "Gündemin tartışılan kararları: iki seçenek, senin tercihin.",
    "Gündem": "Türkiye gündeminden günün haberi, kısa ve net.",
    "Günün Özeti": "Günün öne çıkan haberleri tek videoda.",
    "Bilim ve Teknoloji": "Bilim ve teknolojiden merak uyandıran gelişmeler.",
    "Haftalık Burç Yorumları": "Her pazartesi haftanın gökyüzü olaylarıyla 12 burcun haftalık yorumu.",
    "Haftanın Özeti": "Her pazar haftanın en önemli 10 haberi.",
    "Tarih Belgeselleri": "Tarihin dönüm noktaları, sohbet havasında anlatılan uzun belgeseller.",
    "World News": "One story from world news, explained in English.",
    "History Documentaries": "Turning points of history, told as a conversation.",
}

BY_LABEL = {
    "DİJİTAL PLATFORM": "Netflix ve Dijital Platformlar",
    "KÜLTÜR SANAT": "Dizi, Film ve Kültür-Sanat",
    "BİLİYOR MUYDUN?": "Biliyor muydun?",
    "OTOMOBİL": "Otomobil ve Motor",
    "PARA VE İŞ": "Para ve İş Dünyası",
    "BİLİM VE MÜHENDİSLİK": "Bilim ve Mühendislik",
    "TARİH VE DÜNYA": "Tarih ve Dünya",
    "SPOR": "Spor Haberleri",
    "SEN NE DERSİN?": "Sen Ne Dersin?",
    "GÜNDEM": "Gündem",
    "GÜNÜN ÖZETİ": "Günün Özeti",
    "SABAH ÖZETİ": "Günün Özeti",
    "TREND": "Bilim ve Teknoloji",
    "WORLD": "World News",
}


def for_video(mode, label=""):
    """Videonun listesi; bilinmeyen tür (elle yazılmış özel metin) listeye eklenmez."""
    if (mode or "").startswith("horoscope"):
        return "Haftalık Burç Yorumları"
    return BY_LABEL.get((label or "").strip())
