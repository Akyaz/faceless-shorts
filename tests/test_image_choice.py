import unittest
from unittest import mock

from pipeline import images


class ImageChoice(unittest.TestCase):
    def test_no_bare_city_search(self):
        found = images._searches({"place": {"city": "Istanbul", "country": "Turkey"}, "image_queries": ["stadium"]})
        self.assertNotIn(("Istanbul", False), found)
        self.assertIn(("stadium Istanbul", False), found)

    def test_city_alone_when_nothing_else(self):
        self.assertEqual(images._searches({"place": {"city": "Tokat"}}), [("Tokat", False)])

    def test_media_buildings(self):
        self.assertTrue(images.MEDIA_BUILDINGS.search("File:Kanal D Headquarters.jpg | Kanal D Merkez Binası"))
        self.assertFalse(images.MEDIA_BUILDINGS.search("File:Beyaz Show.jpg | stüdyo"))

    def test_subject_title_must_be_the_name(self):
        def wiki(lang, **p):
            if p.get("list") == "search":
                return {"query": {"search": [{"title": "Yeraltı Camii"}]}}
            raise AssertionError("yanlış sayfaya bakıldı")
        with mock.patch.object(images, "_wiki", wiki):
            self.assertEqual(images.subject_file("Yeraltı"), "")

    def test_recent_images_skipped(self):
        cands = [{"url": "a", "about": "File:A.jpg", "credit": "x", "neutral": False},
                 {"url": "b", "about": "File:B.jpg", "credit": "y", "neutral": False}]
        with mock.patch.object(images, "wikimedia", lambda q, n: cands), \
                mock.patch.object(images, "_select", lambda plan, c: c), \
                mock.patch.object(images, "_save", lambda picked, *a, **k: [(c["url"], c["credit"]) for c in picked]), \
                mock.patch.object(images, "RECENT", {"a"}):
            import pathlib, tempfile
            out = images.find_backgrounds({"image_queries": ["x"], "title": "t", "sources": [{"title": "t"}]},
                                          pathlib.Path(tempfile.mkdtemp()), 2)
        self.assertEqual(out, [("b", "y")])


if __name__ == "__main__":
    unittest.main()
