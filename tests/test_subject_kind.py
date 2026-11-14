"""Görsel kararı konuya göre: yapım, kişi, yer (15 Kasım 2026; Gönül Dağı gündem videosu)."""
import argparse
import pathlib
import tempfile
import unittest
from unittest import mock

from pipeline import main


def args(mode):
    return argparse.Namespace(mode=mode, offline=False)


class Kind(unittest.TestCase):
    def test_kind_order(self):
        self.assertEqual(main.subject_kind({"work_images": [{"url": "a"}], "subject_files": ["f"]}), "yapim")
        self.assertEqual(main.subject_kind({"subject_files": ["f"]}), "kisi")
        self.assertEqual(main.subject_kind({}), "yer")

    def test_series_in_news_slot_uses_stills(self):
        plan = {"work": {"title": "Gönül Dağı"}, "subjects": ["Gönül Dağı"], "sources": [{"title": "h"}]}
        stills = [{"url": "a"}, {"url": "b"}]
        with mock.patch.object(main, "news_plan", return_value=dict(plan)), \
                mock.patch.object(main.platforms, "work_images", return_value=stills), \
                mock.patch.object(main.images, "subject_file", side_effect=AssertionError("kişi fotoğrafı aranmamalı")):
            out = main.with_subject_photos(args("story"))
        self.assertEqual(main.subject_kind(out), "yapim")

    def test_series_without_stills_skipped(self):
        plan = {"work": {"title": "X"}, "subjects": [], "sources": [{"title": "h"}]}
        with mock.patch.object(main, "news_plan", return_value=dict(plan)), \
                mock.patch.object(main.platforms, "work_images", return_value=[{"url": "a"}]):
            with self.assertRaises(RuntimeError):
                main.with_subject_photos(args("story"))

    def test_person_needs_two_photos(self):
        plan = {"work": None, "subjects": ["Ronaldinho"], "sources": [{"title": "h"}]}
        with mock.patch.object(main, "news_plan", return_value=dict(plan)), \
                mock.patch.object(main.images, "subject_file", return_value="File:R.jpg"), \
                mock.patch.object(main.images, "subject_photos", return_value=[]):
            with self.assertRaises(RuntimeError):
                main.with_subject_photos(args("sportstory"))
        with mock.patch.object(main, "news_plan", return_value=dict(plan)), \
                mock.patch.object(main.images, "subject_file", return_value="File:R.jpg"), \
                mock.patch.object(main.images, "subject_photos", return_value=[{"url": "x"}]):
            self.assertEqual(main.subject_kind(main.with_subject_photos(args("sportstory"))), "kisi")

    def test_place_story_allowed_in_news(self):
        plan = {"work": None, "subjects": [], "sources": [{"title": "h"}]}
        with mock.patch.object(main, "news_plan", return_value=dict(plan)):
            self.assertEqual(main.subject_kind(main.with_subject_photos(args("story"))), "yer")
            with self.assertRaises(RuntimeError):  # kültür haberi bir kişi ya da eser hakkında olmalı
                main.with_subject_photos(args("culture"))

    def test_person_has_no_generic_search(self):
        plan = {"segments": [{}] * 4, "subject_files": ["File:R.jpg"], "subjects": ["R"], "image_queries": ["stadium"]}
        work = pathlib.Path(tempfile.mkdtemp())
        def search(p, *a, **k):
            if not p.get("image_files"):
                raise AssertionError("kişi konusunda genel arama yapıldı")
            return [(work / "r.jpg", "c")]

        with mock.patch.object(main.images, "find_backgrounds", side_effect=search) as fb, \
                mock.patch.object(main, "_place_photos", return_value=[]), \
                mock.patch.object(main, "_subject_support", return_value=[(work / "s.jpg", "d")]):
            backgrounds, _ = main.find_images(plan, work)
        self.assertEqual(fb.call_count, 1)  # yalnızca kişinin kendi dosyası
        self.assertEqual(set(backgrounds), {work / "r.jpg", work / "s.jpg"})


class PlaceAndStatues(unittest.TestCase):
    def test_place_search_only_with_city(self):
        plan = {"place": {"city": "Edirne", "country": "Turkey"},
                "image_queries": ["Selimiye Mosque Edirne", "Malcolm Turnbull", "stadium Turkey"]}
        seen = []
        with mock.patch.object(main.images, "find_backgrounds",
                               side_effect=lambda p, *a, **k: seen.append(p["image_queries"]) or []):
            main._place_photos(plan, pathlib.Path(tempfile.mkdtemp()), 2)
            main._place_photos({**plan, "place": {"country": "Italy"}}, pathlib.Path(tempfile.mkdtemp()), 2)
        self.assertEqual(seen, [["Selimiye Mosque Edirne"]])  # şehirsizde arama yok

    def test_bust_not_a_photo_of_the_person(self):
        from pipeline import images
        found = [{"about": "File:Bust of Malcolm Turnbull.jpg | Bust in Ballarat", "url": "b", "year": 2020},
                 {"about": "File:Malcolm Turnbull 2019.jpg | Turnbull", "url": "p", "year": 2019}]
        with mock.patch.object(images, "wikimedia", return_value=found):
            self.assertEqual([c["url"] for c in images.subject_photos("Malcolm Turnbull")], ["p"])

    def test_weak_trends_dropped(self):
        from pipeline import trends
        items = [{"query": "avustralya", "traffic": 100, "news": [{"title": "t", "source": "s", "link": ""}]},
                 {"query": "tev burs", "traffic": 5000, "news": [{"title": "u", "source": "s", "link": ""}]}]
        self.assertEqual([h["trend"] for h in trends.headlines(items)], ["tev burs"])


class SettleScenes(unittest.TestCase):
    """Gerçek görüntü; yoksa grafik; o da yoksa video yok (15 Kasım 2026)."""
    CARD = {"type": "kart", "label": "", "lines": ["x"]}

    def segs(self, n, cards):
        return [{"text": "t", **({"scene": dict(self.CARD)} if i in cards else {})} for i in range(n)]

    def test_photos_keep_one_card_not_first(self):
        plan = {"mode": "story", "segments": self.segs(4, {0, 1, 2, 3})}
        main.settle_scenes(plan, ["a", "b", "a", "b"])
        self.assertEqual([bool(s.get("scene")) for s in plan["segments"]], [False, True, False, False])

    def test_no_photos_all_cards(self):
        plan = {"mode": "story", "segments": self.segs(3, {0, 1, 2})}
        main.settle_scenes(plan, [None, None, None])
        self.assertTrue(all(s.get("scene") for s in plan["segments"]))

    def test_single_photo_without_cards_fails(self):
        plan = {"mode": "story", "segments": self.segs(3, {1})}
        with self.assertRaises(RuntimeError):
            main.settle_scenes(plan, ["a", "a", None])

    def test_fact_series_untouched(self):
        plan = {"segments": self.segs(4, {0, 2})}  # bilgi serisi: mode yok, kendi sahne kararı
        main.settle_scenes(plan, ["a", "b", "a", "b"])
        self.assertEqual([bool(s.get("scene")) for s in plan["segments"]], [True, False, True, False])

    def test_no_city_news_skips_building_search(self):
        plan = {"mode": "story", "segments": [{}] * 3, "place": {"country": "Turkey", "city": ""},
                "image_queries": ["government building"]}
        with mock.patch.object(main.images, "find_backgrounds", side_effect=AssertionError("bina araması")):
            backgrounds, credits = main.find_images(plan, pathlib.Path(tempfile.mkdtemp()))
        self.assertEqual((backgrounds, credits), ([None] * 3, []))


class RejectedText(unittest.TestCase):
    def test_next_story_tried(self):
        from pipeline import script
        heads = [{"title": "kısa haber", "source": "s"}, {"title": "iyi haber", "source": "s"}]
        good = {"title": "t", "segments": [{"text": "x"}], "sources": [heads[1]]}
        calls = []

        def build(h, mode, recent=()):
            calls.append([x["title"] for x in h])
            if h[0]["title"] == "kısa haber":
                raise script.TextRejected("kısa", heads[0])
            return dict(good)
        a = argparse.Namespace(mode="story", offline=False, history=None)
        with mock.patch.object(main.trends, "fetch", return_value=[]), \
                mock.patch("pipeline.news.fetch_headlines", return_value=heads), \
                mock.patch.object(main.script, "build_script", side_effect=build), \
                mock.patch.object(main.review, "check", side_effect=lambda plan, single: plan):
            plan = main.news_plan(a)
        self.assertEqual(plan["sources"], [heads[1]])
        self.assertEqual(calls[1], ["iyi haber"])


if __name__ == "__main__":
    unittest.main()
