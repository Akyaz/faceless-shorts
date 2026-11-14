"""Eski haberde göreli gün ve aynı yapımın tekrarı (Bir Başkadır videosu, 15 Kasım 2026)."""
import unittest
from unittest import mock

from pipeline import main, news, script


class RelativeDay(unittest.TestCase):
    def test_published_in_turkey_time(self):
        self.assertEqual(news._published("Fri, 13 Nov 2026 22:30:00 GMT"), "2026-11-14")  # TSİ 01:30
        self.assertEqual(news._published("bozuk"), "")

    def test_old_story_with_tomorrow_flagged(self):
        texts = ["Yeni sezon yarın Netflix'te yayınlanacak.", "Dizi 14 Kasım'da yayınlandı."]
        self.assertEqual(script.stale_relative(texts, "2026-11-13", "2026-11-15"), texts[:1])
        self.assertEqual(script.stale_relative(texts, "2026-11-15", "2026-11-15"), [])  # bugünün haberi
        self.assertEqual(script.stale_relative(texts, "", "2026-11-15"), [])  # tarih bilinmiyor
        self.assertEqual(script.stale_relative(["Dünkü maçta"], "2026-11-13", "2026-11-15"), ["Dünkü maçta"])
        self.assertEqual(script.stale_relative(["Dünya kupası"], "2026-11-13", "2026-11-15"), [])

    def test_date_shown_to_model(self):
        block = script._blocks([{"title": "Fragman", "source": "Birgün", "published": "2026-11-13"}])[0]
        self.assertIn("yayın: 13 Kasım 2026", block)

    def test_rewrite_then_skip(self):
        old = {"paragraphs": ["Yeni sezon yarın başlıyor."], "title": "t", "hook_title": "", "pick": 1}
        heads = [{"title": "h", "source": "s", "published": "2026-11-13", "related": []}]
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch.object(script, "today_tr", return_value="2026-11-15"), \
                mock.patch.object(script, "_generate", return_value=__import__("json").dumps(old)), \
                mock.patch.object(script, "style_problems", return_value=[]):
            with self.assertRaises(RuntimeError):
                script.story_script(heads, "platform")


class Repeat(unittest.TestCase):
    RECENT = ["Bir Başkadır 2. Sezon Fragmanı Paylaşıldı: Yayın Tarihi Belli Oldu", "Sakıp Sabancı: Stajyerlikten"]

    def test_same_work_or_subject(self):
        plan = {"work": None, "subjects": ["Berkun Oya", "Bir Başkadır"]}
        self.assertEqual(main.repeated(plan, self.RECENT), "Bir Başkadır")
        self.assertEqual(main.repeated({"work": {"title": "Squid Game"}, "subjects": []}, self.RECENT), "")
        self.assertEqual(main.repeated({"subjects": ["Oya"]}, ["Berkun Oyaların"]), "")  # kelime içinde değil


if __name__ == "__main__":
    unittest.main()


class WorkOnly(unittest.TestCase):
    """Dizi ve film haberi: yalnızca yapımın kareleri, adlar kartla, zayıf liste sırası yok (15 Kasım 2026)."""

    def test_card_lines_must_be_in_text(self):
        from pipeline import scenes
        text = "Yeni sezon 14 Kasım'da 4 bölüm olarak yayınlandı. Başrollerde Öykü Karayel ve Fatih Artman var."
        ok = scenes.check({"type": "kart", "label": "Başroller", "lines": ["Öykü Karayel", "Fatih Artman"]}, text)
        self.assertEqual(ok["lines"], ["Öykü Karayel", "Fatih Artman"])
        self.assertIsNone(scenes.check({"type": "kart", "lines": ["Funda Eryiğit"]}, text))  # metinde yok
        self.assertIsNone(scenes.check({"type": "kart", "lines": ["15 Kasım"]}, text))

    def test_card_draws(self):
        from PIL import ImageFont
        from pipeline import scenes
        sc = {"type": "kart", "label": "Yayın", "lines": ["14 Kasım", "4 bölüm"]}
        with mock.patch.object(scenes, "_font", lambda size, bold=True: ImageFont.load_default(size)):
            base, _ = scenes._backdrop(None)
            img = scenes.frame(sc, 2.0, 4.0, base, {"accent": (229, 57, 53), "words": [], "grid": True})
        self.assertEqual(img.size, (scenes.W, scenes.H))

    def test_filler_ending_flagged(self):
        paras = ["Netflix'te bir numara X dizisi.", "Konu.", "Yapım Netflix Türkiye platformunda izleyicilerle "
                 "buluşmayı sürdürüyor."]
        self.assertTrue(script.weak_ending(paras))
        self.assertFalse(script.weak_ending(paras[:2] + ["Dizi 4 bölümden oluşuyor."]))

    def test_only_top_two_ranks(self):
        from pipeline import platforms
        top = [{"category": "TV", "rank": r, "title": f"d{r}", "week": "w", "weeks": 1, "season": ""} for r in (1, 2, 3)]
        top += [{"category": "Films", "rank": 3, "title": "f3", "week": "w", "weeks": 1, "season": ""}]
        searched = []
        with mock.patch.object(platforms, "netflix_top10", return_value=top), \
                mock.patch.object(platforms, "search_headlines", side_effect=lambda q, n: searched.append(q) or []), \
                mock.patch.object(platforms, "PLATFORM_QUERIES", []):
            platforms.headlines()
        self.assertEqual(searched, ['"d1" Netflix', '"d2" Netflix'])

    def test_needs_two_work_images(self):
        import argparse
        args = argparse.Namespace(mode="platform", offline=False)
        plan = {"subjects": ["Berkun Oya"], "sources": [{"title": "h"}], "work": {"title": "X"}}
        one = [{"url": "a"}]
        with mock.patch.object(main, "news_plan", return_value=dict(plan)), \
                mock.patch.object(main.platforms, "work_images", return_value=one), \
                mock.patch.object(main.images, "subject_file", side_effect=AssertionError("Commons aranmamalı")):
            with self.assertRaises(RuntimeError):
                main.with_subject_photos(args)
        with mock.patch.object(main, "news_plan", return_value=dict(plan)), \
                mock.patch.object(main.platforms, "work_images", return_value=one + [{"url": "b"}]):
            self.assertEqual(len(main.with_subject_photos(args)["work_images"]), 2)


class NoCommentCall(unittest.TestCase):
    """Kanalın amacı paylaşım: "yorumlara yaz" çağrısı yok (Ronaldinho videosu, 15 Kasım 2026)."""

    def test_comment_call_flagged(self):
        for text in ["Sen hangi taraftasın? Yorumlara yaz.", "Düşünceni yorumlarda belirt.", "Comment below!"]:
            hard, _ = script.text_problems({"paragraphs": ["a", text]})
            self.assertTrue([h for h in hard if h.startswith("comment call")], text)
        hard, _ = script.text_problems({"paragraphs": ["a", "Derbi 15 Kasım'da başlıyor."]})
        self.assertEqual([h for h in hard if h.startswith("comment call")], [])

    def test_short_text_is_hard(self):
        hard, _ = script.text_problems({"paragraphs": ["Galatasaray 82-81 yenildi.", "Son saniye basketi."]})
        self.assertTrue(any(h.startswith("metin çok kısa") for h in hard))


class SingleRewrite(unittest.TestCase):
    """Metin bir kez yeniden yazdırılır: kesin sorun kalırsa video çıkmaz, üslup sorunu kalırsa daha azı seçilir."""
    HEADS = [{"title": "h", "source": "s", "published": "", "related": []}]

    def run_with(self, *replies):
        import json
        calls = iter(json.dumps(r) for r in replies)
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch.object(script, "_generate", side_effect=lambda *a, **k: next(calls)):
            return script.story_script(self.HEADS, "story")

    def test_hard_problem_left_skips_video(self):
        bad = {"paragraphs": ["Kısa.", "Sen hangi taraftasın? Yorumlara yaz."], "title": "t", "pick": 1}
        with self.assertRaises(RuntimeError):
            self.run_with(bad, bad)

    def test_fixed_text_used(self):
        bad = {"paragraphs": ["Kısa.", "Sen hangi taraftasın? Yorumlara yaz."], "title": "t", "pick": 1}
        good = {"paragraphs": ["Okullar yarın kapalı."] + ["Bilgi cümlesi burada yer alıyor."] * 12,
                "title": "t", "pick": 1}
        plan = self.run_with(bad, good)
        self.assertEqual(plan["segments"][0]["text"], "Okullar yarın kapalı.")

    def test_custom_paragraph_scene(self):
        item = {"title": "t", "sources": [{"title": "s", "source": "x"}],
                "paragraphs": [{"text": "46 yaşındaki yıldız 11 yıl sonra sahada.",
                                "scene": {"type": "kart", "lines": ["46 yaşında", "11 yıl sonra"]}},
                               {"text": "Maç bugün.", "scene": {"type": "kart", "lines": ["20.30"]}}]}
        segs = script.custom_plan(item)["segments"]
        self.assertEqual(segs[0]["scene"]["lines"], ["46 yaşında", "11 yıl sonra"])
        self.assertNotIn("scene", segs[1])  # satır metinde yok
