"""Wikimedia dışındaki görsel ve video kaynakları (14 Kasım 2026)."""
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from pipeline import images, render

PLAN = {"image_queries": ["bridge"], "title": "t", "sources": [{"title": "t"}]}


class Openverse(unittest.TestCase):
    def test_parses_and_skips_commons(self):
        data = {"results": [
            {"source": "wikimedia", "url": "https://upload.wikimedia.org/a.jpg", "license": "by"},
            {"source": "flickr", "category": "photograph", "title": "1915 Canakkale Bridge",
             "url": "https://live.staticflickr.com/1/2_abc_b.jpg", "license": "by-sa", "license_version": "2.0",
             "creator": "Joker", "foreign_landing_url": "https://flickr.com/p/2", "width": 1024, "height": 768,
             "tags": [{"name": "canakkale"}]},
        ]}
        with mock.patch.object(images, "_get_json", return_value=data):
            found = images.openverse("bridge")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["preview"], "https://live.staticflickr.com/1/2_abc_n.jpg")
        self.assertIn("CC BY-SA 2.0, Flickr (https://flickr.com/p/2)", found[0]["credit"])
        self.assertIn("canakkale", found[0]["about"])

    def test_media_buildings_skipped(self):
        data = {"results": [{"source": "flickr", "title": "Kanal D headquarters", "url": "u", "license": "by",
                             "foreign_landing_url": "x"}]}
        with mock.patch.object(images, "_get_json", return_value=data):
            self.assertEqual(images.openverse("x"), [])


class Stock(unittest.TestCase):
    def test_no_key_no_request(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(images, "_get_json", side_effect=AssertionError("istek atıldı")):
            self.assertEqual(images.pixabay("x"), [])
            self.assertEqual(images.pexels("x", video=True), [])

    def test_pixabay_video_picks_hd_file(self):
        data = {"hits": [{"tags": "bridge, sea", "user": "ali", "pageURL": "https://pixabay.com/v/1",
                          "videos": {"large": {"url": "L", "width": 3840, "height": 2160, "thumbnail": "tl"},
                                     "medium": {"url": "M", "width": 1920, "height": 1080, "thumbnail": "tm"},
                                     "small": {"url": "S", "width": 1280, "height": 720, "thumbnail": "ts"},
                                     "tiny": {"url": "T", "width": 640, "height": 360, "thumbnail": "tt"}}}]}
        with mock.patch.dict(os.environ, {"PIXABAY_API_KEY": "k"}), \
                mock.patch.object(images, "_get_json", return_value=data):
            found = images.pixabay("bridge", video=True)
        self.assertEqual(found[0]["video"], "S")  # 720p'nin altı bulanık, 4K gereksiz büyük
        self.assertEqual(found[0]["url"], "tm")
        self.assertTrue(found[0]["credit"].startswith("Video: ali, Pixabay lisansı"))

    def test_pexels_video(self):
        data = {"videos": [{"url": "https://www.pexels.com/video/aerial-view-of-a-bridge-123/", "image": "poster",
                            "user": {"name": "Ayşe"},
                            "video_files": [{"link": "sd", "width": 640, "height": 360},
                                            {"link": "hd", "width": 1080, "height": 1920}]}]}

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return __import__("json").dumps(data).encode()
        with mock.patch.dict(os.environ, {"PEXELS_API_KEY": "k"}), \
                mock.patch("urllib.request.urlopen", return_value=Resp()):
            found = images.pexels("bridge", video=True)
        self.assertEqual(found[0]["video"], "hd")
        self.assertIn("aerial view of a bridge", found[0]["about"])

    def test_no_videos_for_wide(self):
        names = [n for n, _ in images._sources({"wide": True})]
        self.assertNotIn("Pexels video", names)
        self.assertIn("Pexels video", [n for n, _ in images._sources({})])
        self.assertIn("NASA", [n for n, _ in images._sources({"kind": "fact"})])

    def test_stock_tagged_for_model(self):
        self.assertEqual(images._tags({"source": "pexels", "video": "v"}), "[stok] [video] ")
        self.assertEqual(images._tags({"source": "openverse"}), "")


class StockGuard(unittest.TestCase):
    PLAN = {"kind": "fact", "sources": [{"title": "Anadol (otomobil)"}], "place": {"country": "Turkey"}}

    def test_generic_stock_rejected(self):
        names = images._names(self.PLAN)
        self.assertEqual(names, {"anadol"})
        car = {"about": "vintage car, classic car, yellow car | Pixabay", "neutral": False}
        self.assertFalse(images._stock_ok(car, names))
        self.assertTrue(images._stock_ok({**car, "about": "anadol, otomobil | Pixabay"}, names))

    def test_object_query_allows_generic(self):
        self.assertTrue(images._stock_ok({"about": "steering wheel", "neutral": True}, set()))

    def test_filter_applied_in_search(self):
        stock = [{"url": "s", "about": "classic car", "credit": "x", "source": "pixabay"}]
        shown = []
        with mock.patch.object(images, "_sources", lambda plan: [("Pixabay", lambda q, n: stock)]), \
                mock.patch.object(images, "_select", lambda plan, c: shown.extend(c) or c), \
                mock.patch.object(images, "_save", lambda picked, *a, **k: []), \
                mock.patch.object(images, "RECENT", set()):
            images.find_backgrounds({**self.PLAN, "image_queries": ["Anadol car"], "title": "t"},
                                    pathlib.Path(tempfile.mkdtemp()), 2)
        self.assertEqual(shown, [])


class Fallback(unittest.TestCase):
    def test_without_vetting_only_commons(self):
        cands = [{"url": "p", "about": "a", "credit": "x", "source": "pexels"},
                 {"url": "c", "about": "b", "credit": "y", "source": "commons"}]
        with mock.patch.object(images, "_sources", lambda plan: [("x", lambda q, n: cands)]), \
                mock.patch.object(images, "_select", lambda plan, c: None), \
                mock.patch.object(images, "_save", lambda picked, *a, **k: [(c["url"], c["credit"]) for c in picked]), \
                mock.patch.object(images, "RECENT", set()):
            out = images.find_backgrounds(PLAN, pathlib.Path(tempfile.mkdtemp()), 2)
        self.assertEqual(out, [("c", "y")])


class Clip(unittest.TestCase):
    def test_video_saved_next_to_poster(self):
        out = pathlib.Path(tempfile.mkdtemp())
        got = []
        with mock.patch.object(images, "_download", lambda url, path: (got.append(url), path.write_bytes(b"x"))):
            res = images._save([{"url": "poster", "video": "clip", "about": "a", "credit": "Video: z"}], out, 1)
        self.assertEqual(got, ["poster", "clip"])
        self.assertTrue((out / "background0.mp4").exists())
        self.assertEqual(res, [(out / "background0.jpg", "Video: z")])

    def test_card_gets_clip(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "background0.mp4").write_bytes(b"v")
        render._attach_clip(d / "background0.jpg", d / "card0.png")
        self.assertTrue((d / "card0.bg.mp4").exists())
        render._attach_clip(d / "other.jpg", d / "card0.png")  # fotoğraflı kartta eski klip kalmasın
        self.assertFalse((d / "card0.bg.mp4").exists())

    def test_nasa_resolves_size(self):
        files = ["http://x/a~orig.jpg", "http://x/a~medium.jpg", "http://x/a~thumb.jpg"]
        with mock.patch.object(images, "_get_json", return_value=files):
            self.assertEqual(images._resolve("http://x/collection.json"), "https://x/a~medium.jpg")
        self.assertEqual(images._resolve("https://a/b.jpg"), "https://a/b.jpg")


if __name__ == "__main__":
    unittest.main()
