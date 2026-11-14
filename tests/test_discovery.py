import unittest
from unittest import mock

from pipeline import captions, playlists, upload


class Captions(unittest.TestCase):
    def test_srt_timing_and_text(self):
        out = captions.srt([(0.5, 4.0, "Lupin Netflix'te dördüncü sırada. Dizi üç haftadır listede."),
                            (5.0, 2.0, "Yeni sezon 23 Ekim'de yayınlandı.")])
        blocks = out.strip().split("\n\n")
        self.assertEqual(len(blocks), 3)
        self.assertTrue(blocks[0].startswith("1\n00:00:00,500 --> "))
        self.assertIn("Lupin Netflix'te dördüncü sırada.", blocks[0])
        self.assertIn("00:00:05,000 --> 00:00:07,000", blocks[2])

    def test_long_sentence_split_without_orphans(self):
        parts = captions._chunks(" ".join(f"k{i}" for i in range(11)))
        self.assertEqual([len(p.split()) for p in parts], [6, 5])


class Playlists(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(playlists.for_video("platform", "DİJİTAL PLATFORM"), "Netflix ve Dijital Platformlar")
        self.assertEqual(playlists.for_video("fact", "OTOMOBİL"), "Otomobil ve Motor")
        self.assertEqual(playlists.for_video("horoscope2", "KOÇ"), "Haftalık Burç Yorumları")
        self.assertIsNone(playlists.for_video("story", "ÖZEL"))

    def test_every_target_has_description(self):
        for title in set(playlists.BY_LABEL.values()) | {"Maç Programı", "Haftanın Özeti", "Tarih Belgeselleri"}:
            self.assertTrue(playlists.PLAYLISTS.get(title), title)


class Upload(unittest.TestCase):
    def test_playlist_created_when_missing_then_video_added(self):
        calls = []

        def call(method, url, token, body=None, **kw):
            calls.append((method, url.split("?")[0].rsplit("/", 1)[-1], body))
            if method == "GET":
                return {"items": [{"id": "X", "snippet": {"title": "Başka"}}]}
            return {"id": "NEW"}
        with mock.patch.object(upload, "_call", call):
            upload.add_to_playlist("t", "vid", "Otomobil ve Motor")
        self.assertEqual([c[:2] for c in calls], [("GET", "playlists"), ("POST", "playlists"), ("POST", "playlistItems")])
        self.assertEqual(calls[2][2]["snippet"]["playlistId"], "NEW")

    def test_caption_failure_does_not_raise(self):
        with mock.patch.object(upload, "_call", side_effect=OSError("koptu")):
            upload.add_captions("t", "vid", "1\n00:00:00,000 --> 00:00:01,000\nMerhaba\n\n")


if __name__ == "__main__":
    unittest.main()


class Numbers(unittest.TestCase):
    def test_number_not_split(self):
        parts = captions._chunks("2024 yılında bu köprüden 2 milyon 684 bin 738 araç geçti.")
        self.assertTrue(any("2 milyon 684 bin 738" in p for p in parts), parts)
