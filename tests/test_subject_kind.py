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
                mock.patch.object(main, "_subject_support", return_value=[(work / "s.jpg", "d")]):
            backgrounds, _ = main.find_images(plan, work)
        self.assertEqual(fb.call_count, 1)  # yalnızca kişinin kendi dosyası
        self.assertEqual(set(backgrounds), {work / "r.jpg", work / "s.jpg"})


if __name__ == "__main__":
    unittest.main()
