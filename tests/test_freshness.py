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
