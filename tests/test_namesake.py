"""Adaş kişi ve kurumlar: Carlos Cuesta videosunda İspanyol gazetecinin fotoğrafları ve kâşif Vasco da Gama'nın
portresi çıktı (17 Kasım 2026)."""
import unittest
from unittest import mock

from pipeline import images

NEWS = "Carlos Cuesta, Galatasaray'a geri dönüyor - Vasco da Gama opsiyonu kullanmayacak"


def wiki(lang, **params):
    if params.get("list") == "search":
        return {"query": {"search": [{"title": "Vasco da Gama"}]}}
    return {"query": {"pages": [{"description": "Portekizli kâşif", "original": {
        "source": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Portrait_1525.jpg"}}]}}


class Namesake(unittest.TestCase):
    def setUp(self):
        images._same_subject.clear()

    def test_subject_file_rejects_namesake(self):
        with mock.patch.object(images, "_wiki", side_effect=wiki), \
                mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch("pipeline.script._generate", return_value='{"pick": []}') as gen:
            self.assertEqual(images.subject_file("Vasco da Gama", NEWS), "")
        self.assertIn("Portekizli kâşif", gen.call_args[0][0])
        self.assertIn(NEWS, gen.call_args[0][0])

    def test_subject_file_without_context_unchanged(self):
        with mock.patch.object(images, "_wiki", side_effect=wiki), \
                mock.patch("pipeline.script._generate") as gen:
            self.assertEqual(images.subject_file("Vasco da Gama"), "File:Portrait 1525.jpg")
        gen.assert_not_called()

    def test_vet_photos_looks_at_photos_with_news(self):
        # 19 Kasım 2026: Fenerbahçe haberinde Efes formalı Larkin, Arda Güler haberinde başka bir Real Madrid oyuncusu
        cands = [{"about": "File:Shane Larkin Efes 2023.jpg", "url": "a"}, {"about": "File:Shane Larkin FB.jpg", "url": "b"},
                 {"about": "File:Shane Larkin FB.jpg", "url": "b"}]
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch.object(images, "_preview", return_value=b"x"), \
                mock.patch("pipeline.script._generate", return_value='{"pick": [2]}') as gen:
            self.assertEqual([c["url"] for c in images.vet_photos(["Shane Larkin"], "Fenerbahçe Beko kazandı", cands)], ["b"])
        prompt, shown = gen.call_args[0][0], gen.call_args[0][2]
        self.assertIn("Fenerbahçe Beko kazandı", prompt)
        self.assertIn("başka takımın formasıyla", prompt)
        self.assertEqual(len(shown), 2)  # aynı fotoğraf iki kez gösterilmez

    def test_vet_photos_failure_keeps_nothing(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch.object(images, "_preview", return_value=b"x"), \
                mock.patch("pipeline.script._generate", side_effect=RuntimeError("429")):
            self.assertEqual(images.vet_photos(["X"], NEWS, [{"about": "a", "url": "a"}]), [])

    def test_model_failure_keeps_nothing(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch("pipeline.script._generate", side_effect=RuntimeError("503")):
            self.assertEqual(images.same_subject("X", NEWS, ["aday"]), set())


if __name__ == "__main__":
    unittest.main()
