"""Animasyonlu sahneler: sayı denetimi, harita koordinatı, fotoğraf dağıtımı ve çizim (14 Kasım 2026)."""
import unittest
from unittest import mock

from PIL import ImageFont

from pipeline import scenes

TEXT = "Sakıp Sabancı 1948 yılında Akbank'ta başladı. 1966'da holdingin başına geçti. Servet 3,2 milyar dolar, " \
       "22.413 dalış yapıldı."


class Numbers(unittest.TestCase):
    def test_parse_and_format_keep_text_style(self):
        self.assertEqual(scenes.parse("3,2"), (3.2, 1, False))
        self.assertEqual(scenes.parse("22.413"), (22413.0, 0, True))
        self.assertEqual(scenes.fmt(22413, 0, True), "22.413")
        self.assertEqual(scenes.fmt(1966, 0, False), "1966")  # yıl "1.966" olmaz
        self.assertEqual(scenes.fmt(1.6, 1, False), "1,6")
        self.assertIsNone(scenes.parse("üç"))

    def test_number_must_be_in_paragraph(self):
        ok = scenes.check({"type": "sayac", "value": "3,2", "unit": "milyar dolar", "label": "Servet"}, TEXT)
        self.assertEqual(ok["value"], "3,2")
        self.assertEqual(scenes.check({"type": "sayac", "value": 3.2, "unit": "milyar"}, TEXT)["value"], "3,2")
        self.assertIsNone(scenes.check({"type": "sayac", "value": "4", "unit": "milyar"}, TEXT))  # uydurma
        # Etiketteki sayı da metinden olmalı
        self.assertIsNone(scenes.check({"type": "sayac", "value": "22.413", "label": "10 yılda"}, TEXT))

    def test_timeline_and_compare(self):
        tl = scenes.check({"type": "zaman", "points": [{"year": "1966", "label": "Holding"},
                                                       {"year": "1948", "label": "Akbank"}]}, TEXT)
        self.assertEqual([p["year"] for p in tl["points"]], ["1948", "1966"])  # sıraya dizilir
        self.assertIsNone(scenes.check({"type": "zaman", "points": [{"year": "1948"}, {"year": "1950"}]}, TEXT))
        self.assertIsNone(scenes.check({"type": "karsilastirma", "items": [{"name": "a", "value": "1948"}]}, TEXT))
        self.assertIsNone(scenes.check({"type": "bilinmeyen"}, TEXT))

    def test_long_label_rejected(self):
        self.assertIsNone(scenes.check({"type": "sayac", "value": "3,2", "label": "x" * 40}, TEXT))


class Prepare(unittest.TestCase):
    def test_map_needs_place_in_text_and_coordinates(self):
        paras = ["Batık 1982'de Kaş açıklarında bulundu.", "Ankara'da sergilendi.", "Üçüncü paragraf."]
        raw = [{"paragraph": 1, "type": "harita", "place": "Kaş", "label": "Kaş açıkları"},
               {"paragraph": 2, "type": "harita", "place": "İzmir"},  # paragrafta geçmiyor
               {"paragraph": 3, "type": "harita", "place": "Üçüncü"}]
        with mock.patch.object(scenes, "coords", side_effect=[(36.2, 29.64), None]) as geo:
            got = scenes.prepare(paras, raw)
        self.assertEqual(list(got), [0])  # Üçüncü: koordinat yok
        self.assertEqual((got[0]["lat"], got[0]["lon"]), (36.2, 29.64))
        self.assertEqual(geo.call_count, 2)

    def test_at_most_two_one_per_paragraph(self):
        paras = [TEXT] * 4
        raw = [{"paragraph": k, "type": "sayac", "value": "3,2"} for k in (1, 1, 2, 3, 4)] + ["bozuk", {"x": 1}]
        self.assertEqual(sorted(scenes.prepare(paras, raw)), [0, 1])
        self.assertEqual(scenes.prepare(paras, None), {})


    def test_limit_raised_when_topic_has_no_photo(self):
        paras = [TEXT] * 4
        raw = [{"paragraph": k, "type": "sayac", "value": "3,2"} for k in (1, 2, 3, 4)]
        self.assertEqual(len(scenes.prepare(paras, raw, 3)), 3)


class ChosenTopic(unittest.TestCase):
    def test_topic_from_list_or_free(self):
        from pipeline import evergreen
        rows = [("tarih", "Uluburun batığı", "Uluburun shipwreck"), ("para", "Sakıp Sabancı", "Sakıp Sabancı")]
        self.assertEqual(evergreen.chosen_topic(rows, "uluburun Batığı")[0], "tarih")
        self.assertEqual(evergreen.chosen_topic(rows, "Sakıp Sabancı")[0], "para")
        self.assertEqual(evergreen.chosen_topic(rows, "Kapadokya"), ("bilgi", "Kapadokya", "Kapadokya"))


class Spread(unittest.TestCase):
    def test_photos_go_to_plain_paragraphs_first(self):
        segs = [{}, {"scene": {"type": "sayac"}}, {}, {}]
        # Eskisi: iki fotoğraf dört paragrafta a, b, a, b
        out = scenes.spread(["a", "b", "a", "b"], segs)
        self.assertEqual([out[0], out[2], out[3]], ["a", "b", "a"])
        self.assertIn(out[1], ("a", "b"))  # sahnenin bulanık zemini

    def test_unused_photo_becomes_scene_backdrop(self):
        segs = [{}, {"scene": {"type": "zaman"}}, {}]
        self.assertEqual(scenes.spread(["a", "b", "c"], segs), ["a", "c", "b"])

    def test_no_scene_no_change(self):
        self.assertEqual(scenes.spread(["a", None], [{}, {}]), ["a", None])


class Draw(unittest.TestCase):
    WORDS = [{"text": w, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, w in enumerate(TEXT.split())]

    def setUp(self):
        fonts = mock.patch.object(scenes, "_font", lambda size, bold=True: ImageFont.load_default(size))
        fonts.start()
        self.addCleanup(fonts.stop)

    def test_counter_finishes_when_number_is_said(self):
        self.assertAlmostEqual(scenes._said(self.WORDS, "1966"), 2.4)  # 7. kelime: "1966'da"
        self.assertIsNone(scenes._said(self.WORDS, "2000"))

    def test_every_type_draws(self):
        ctx = {"accent": (229, 57, 53), "words": self.WORDS, "grid": True}
        base, _ = scenes._backdrop(None)
        cases = [{"type": "sayac", "value": "22.413", "unit": "dalış", "label": "Toplam"},
                 {"type": "karsilastirma", "label": "", "unit": "m",
                  "items": [{"name": "A", "value": "1.991"}, {"name": "B", "value": "2.023"}]},
                 {"type": "zaman", "points": [{"year": "1948", "label": "Akbank"}, {"year": "1966", "label": ""}]}]
        for sc in cases:
            for t in (0, 1.0, 5.9):
                img = scenes.frame(sc, t, 6.0, base, ctx)
                self.assertEqual(img.size, (scenes.W, scenes.H))

    def test_map_draws_with_land(self):
        ctx = {"accent": (229, 57, 53), "words": [], "grid": False}
        img = scenes.frame({"type": "harita", "place": "Kaş", "label": "Kaş", "lat": 36.2, "lon": 29.64},
                           3.0, 4.0, None, ctx)
        colors = {c for _, c in img.resize((54, 96)).getcolors(10000)}
        self.assertTrue(any(abs(c[0] - scenes.LAND[0]) < 6 and abs(c[2] - scenes.LAND[2]) < 6 for c in colors))


if __name__ == "__main__":
    unittest.main()
