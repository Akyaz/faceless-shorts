"""Yazılan metni haberin kendisine karşı denetler: izleyicinin aklında soru bırakan eksikleri ve yanlışları
Google Arama ile bulup giderir.

Metin yalnızca Google News başlıklarından yazılıyor ve başlıkta olmayan bilgi eklenmiyor. Bu yüzden "5 ilçede su
kesintisi" deyip hangi ilçeler olduğunu, "kupadan men edildi" deyip nedenini söylemeyen videolar çıkıyordu.
Denetçi aynı olayı haberlerde arar, eksik bilgiyi bulursa metne ekler. Bulamazsa haber atlanır, belirsiz video
yayınlanmaz.
"""
import datetime
import json
import os
import re

from . import script

TURKEY = datetime.timezone(datetime.timedelta(hours=3))
MAX_WORDS = 110  # seslendirme bir dakikayı aşmasın


class Incomplete(Exception):
    """Metindeki eksik ya da yanlış bilgi doğrulanabilir kaynaklarla giderilemedi."""


RULES_TR = """Görev: Aşağıdaki YouTube Shorts haber metnini yayından önce bir editör gibi denetle. Bugün {today}.

1. İzleyici gözüyle oku: metin, başlık ya da ekran başlığı cevabını vermediği bir soru bırakıyor mu? Örnek:
   "5 ilçede su kesintisi" deyip hangi ilçeler olduğunu, saatini söylememek; "kupadan men edildi" deyip nedenini
   ve süresini söylememek; "zam geldi" deyip ne kadar olduğunu söylememek; "açıklama yaptı" deyip ne dendiğini
   söylememek. Haberin özünü anlamak için gereken eksikleri listele (her ayrıntı değil, merak bırakan asıl bilgi).
2. Google Arama ile bu olayı (aynı gün, aynı olay) güvenilir haber sitelerinde ve resmî kaynaklarda ara. Eksik
   bilgileri bul ve metindeki her iddianın doğru olduğunu kontrol et.
3. Karar:
   - "ok": eksik ve yanlış yok; metni değiştirme.
   - "fixed": eksikleri bulduğun bilgilerle tamamla, yanlışları düzelt. Yalnızca gereken cümleleri değiştir.
     Paragraf sayısı, ilk cümle, son soru, üslup ve yapı aynı kalsın. Toplam en fazla {max_words} kelime;
     yer açmak için daha az önemli bir cümleyi kısalt. Uzun bir liste (6'dan fazla ilçe gibi) seslendirmeye
     sığmıyorsa en çok etkilenenleri ya da somut bir gruplamayı söyle ("Avrupa yakasındaki 7 ilçe: ..." gibi).
   - "unfixable": metnin bıraktığı asıl soru kaynaklarda cevaplanmıyor ya da haber doğrulanamıyor.
4. Kesin kurallar: Yalnızca aramada bulduğun ve bu olayla ilgili bilgileri ekle; tahmin, yorum ve uydurma yok.
   Talebi karar gibi sunma. 18 yaşından küçüklerin, mağdurların ve kamuya mal olmamış kişilerin adını yazma.
   Can kaybı ve mağduriyet içeren haberlerde sade ve saygılı dil, ayrıntı yok. "Kaynaklara göre",
   "habere göre" gibi dolgu ekleme. Türkçe yaz.
5. pronounce: eklediğin Türkçe olmayan özel isimlerin Türkçe harflerle okunuşu (yoksa boş).

Kaynak başlıklar (metin bunlardan yazıldı):
{sources}

{content}

Yanıtı yalnızca JSON olarak ver, başka metin yazma:
{schema}
"""

RULES_EN = """Task: act as an editor and check the YouTube Short news script below before it is published. Today is {today}.

1. Read it as a viewer: does the script, title or on-screen title leave a question it does not answer? For example
   "water cut in 5 districts" without saying which districts; "banned from the cup" without saying why or for how
   long; "made a statement" without saying what was said. List the gaps a viewer needs filled to understand the
   story (the key missing fact, not every detail).
2. Use Google Search to find this exact event (same day, same story) in reliable news outlets and official sources.
   Find the missing facts and check that every claim in the script is correct.
3. Decide:
   - "ok": nothing missing or wrong; do not change the script.
   - "fixed": fill the gaps with what you found and correct any errors. Change only the sentences that need it.
     Keep the number of paragraphs, the first sentence, the final question, the tone and the structure. At most
     {max_words} words in total; shorten a less important sentence to make room.
   - "unfixable": the key question the script raises is not answered by any source, or the story cannot be verified.
4. Strict rules: add only facts you found in the search about this event; no guessing, opinion or invention. Do not
   present a demand as a decision. Do not name minors, victims or private individuals. Report loss of life plainly
   and respectfully, without detail. No filler such as "according to reports". Write in English.
5. pronounce: leave empty.

Source headlines (the script was written from these):
{sources}

{content}

Reply with JSON only, no other text:
{schema}
"""

STORY_SCHEMA = ('{"questions": ["..."], "status": "ok|fixed|unfixable", "title": "...", "hook_title": "...", '
                '"paragraphs": ["..."], "pronounce": {}, "note": "neyi neden değiştirdin"}')
DIGEST_SCHEMA = ('{"items": [{"n": 1, "questions": ["..."], "status": "ok|fixed|unfixable", "heading": "...", '
                 '"text": "..."}], "pronounce": {}}')


def _today(english):
    now = datetime.datetime.now(TURKEY)
    return now.strftime("%d %B %Y") if english else now.strftime("%d.%m.%Y")


def _sources(plan):
    lines = []
    for h in plan["sources"]:
        lines.append(f"- {h['title']} ({h.get('source', '')})")
        lines += [f"  - {r['title']} ({r.get('source', '')})" for r in h.get("related", [])[:6]]
    return "\n".join(lines)


def _json(text):
    """Arama açıkken JSON yanıt biçimi zorlanamıyor; model kod bloğu ya da açıklama ekleyebilir."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"Denetçi JSON döndürmedi: {text[:200]}")
    return json.loads(text[start:end + 1])


def _ask(prompt):
    """(yanıt, aramada kullanılan kaynak adresleri)."""
    body = {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]}
    candidate = script._call(body, os.environ["GEMINI_API_KEY"])
    chunks = (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []
    links = [c["web"].get("title") or c["web"].get("uri") for c in chunks if c.get("web")]
    return _json(script._parts_text(candidate)), links


def _words(texts):
    return sum(len(t.split()) for t in texts)


def _prompt(plan, content, schema):
    english = plan.get("lang") == "en"
    return (RULES_EN if english else RULES_TR).format(today=_today(english), max_words=MAX_WORDS,
                                                      sources=_sources(plan), content=content, schema=schema)


def check_story(plan):
    """Tek konulu video. Düzeltilmiş planı döndürür; giderilemeyen eksikte Incomplete."""
    paragraphs = [s["text"] for s in plan["segments"]]
    content = (f"YouTube başlığı: {plan['title']}\nEkran başlığı: {plan.get('hook_title', '')}\nMetin (paragraflar):\n"
               + "\n".join(f"{i}. {p}" for i, p in enumerate(paragraphs, 1)))
    out, links = _ask(_prompt(plan, content, STORY_SCHEMA))
    status, questions = out.get("status"), out.get("questions") or []
    print(f"Metin denetimi: {status}; sorular: {questions}; kaynaklar: {links[:5]}")
    if status == "ok":
        return plan
    if status != "fixed":
        raise Incomplete(f"eksik bilgi bulunamadı: {'; '.join(questions) or out.get('note', '')}")
    new = [str(p).strip() for p in out.get("paragraphs") or [] if str(p).strip()]
    title = str(out.get("title") or plan["title"]).strip()
    hook = str(out.get("hook_title") or plan.get("hook_title", "")).strip()
    # Arama yapmadan "düzelttim" diyen yanıt bilgiyi uydurmuş olabilir; yapıyı bozan ya da uzayan metin seslendirmeye
    # ve tartışma videosunun düzenine uymaz
    problem = ("arama kaynağı yok" if not links else
               "paragraf sayısı değişti" if len(new) != len(paragraphs) else
               f"{_words(new)} kelime" if _words(new) > MAX_WORDS else
               "belirsiz cümle" if any(script.vague(t) for t in new + [title, hook]) else "")
    if problem:
        raise Incomplete(f"düzeltme kullanılamadı ({problem}): {'; '.join(questions)}")
    for old, text in zip(paragraphs, new):
        if old != text:
            print(f"  - {old}\n  + {text}")
    print(f"  Not: {out.get('note', '')}")
    segments = [{**s, "text": t} for s, t in zip(plan["segments"], new)]
    pronounce = {**script._pronounce(out), **(plan.get("pronounce") or {})}
    return {**plan, "title": title[:100], "hook_title": hook, "segments": segments, "pronounce": pronounce}


def check_digest(plan):
    """Toplu özet: eksiği giderilemeyen madde çıkarılır; iki maddeden az kalırsa Incomplete."""
    items = [s for s in plan["segments"] if s["kind"] == "item"]
    content = "Maddeler (her biri ayrı bir haber; kaynak başlığı yanında):\n" + "\n".join(
        f"{i}. Ekran başlığı: {s.get('heading', '')} | Metin: {s['text']} | Kaynak başlık: {s['headline']['title']}"
        for i, s in enumerate(items, 1))
    out, links = _ask(_prompt(plan, content, DIGEST_SCHEMA))
    verdicts = {int(v["n"]): v for v in out.get("items") or [] if str(v.get("n", "")).isdigit()}
    print(f"Metin denetimi: {[(n, v.get('status')) for n, v in sorted(verdicts.items())]}; kaynaklar: {links[:5]}")
    kept = []
    for i, seg in enumerate(items, 1):
        v = verdicts.get(i, {"status": "ok"})
        text, heading = str(v.get("text") or "").strip(), str(v.get("heading") or seg.get("heading", "")).strip()
        if v.get("status") == "fixed" and links and text and len(text.split()) <= 30 and not script.vague(text):
            print(f"  - {seg['text']}\n  + {text}")
            seg = {**seg, "text": script._sentence(text), "heading": heading}
        elif v.get("status") != "ok":
            print(f"  Madde çıkarıldı ({'; '.join(v.get('questions') or [])}): {seg['text']}")
            continue
        kept.append(seg)
    if len(kept) < 2:
        raise Incomplete("özette eksiksiz anlatılabilen yeterli madde kalmadı")
    total = len(kept)
    for i, seg in enumerate(kept, 1):  # "SPOR 2/4" etiketleri kalan madde sayısına göre
        seg["label"] = re.sub(r"\d+/\d+$", f"{i}/{total}", seg.get("label", ""))
    intro = [{**s, "text": recount(s["text"], len(items), total)} for s in plan["segments"] if s["kind"] == "intro"]
    segments = intro + kept + [s for s in plan["segments"] if s["kind"] == "outro"]
    pronounce = {**script._pronounce(out), **(plan.get("pronounce") or {})}
    return {**plan, "title": recount(plan["title"], len(items), total), "segments": segments,
            "sources": [s["headline"] for s in kept], "pronounce": pronounce}


NUMBERS = {2: "iki", 3: "üç", 4: "dört", 5: "beş", 6: "altı"}


def recount(text, old, new):
    """Madde çıkarılınca "Bugünün beş haberi" gibi sayılar kalan maddeye göre düzelir."""
    if old == new or old not in NUMBERS:
        return text

    def swap(m):
        word = m.group(0)
        if word.isdigit():
            return str(new)
        return NUMBERS[new].capitalize() if word[0].isupper() else NUMBERS[new]
    return re.sub(rf"(?<!\w)({old}|{NUMBERS[old]}|{NUMBERS[old].capitalize()})(?!\w)", swap, text)


def check(plan, single):
    """Denetçi yanıt veremezse (yoğunluk, kota) metin denetimsiz kullanılır: önceki davranış budur ve saat
    boşa gitmesin. Eksik bilgi bulunamazsa Incomplete yükselir."""
    if os.environ.get("REVIEW", "1") == "0" or not os.environ.get("GEMINI_API_KEY"):
        return plan
    try:
        return check_story(plan) if single else check_digest(plan)
    except Incomplete:
        raise
    except Exception as exc:
        print(f"Metin denetimi yapılamadı, metin olduğu gibi kullanılıyor: {exc}")
        return plan
