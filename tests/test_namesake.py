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

    def test_subject_photos_keeps_only_matching(self):
        found = [{"about": "File:Carlos Cuesta 2014.jpg | Carlos Cuesta, HazteOir.org", "year": 2014, "url": "a"},
                 {"about": "File:Carlos Cuesta Galatasaray 2024.jpg | Colombian footballer", "year": 2024, "url": "b"}]
        with mock.patch.object(images, "wikimedia", return_value=found), \
                mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch("pipeline.script._generate", return_value='{"pick": [2]}'):
            self.assertEqual([c["url"] for c in images.subject_photos("Carlos Cuesta", context=NEWS)], ["b"])

    def test_model_failure_keeps_nothing(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch("pipeline.script._generate", side_effect=RuntimeError("503")):
            self.assertEqual(images.same_subject("X", NEWS, ["aday"]), set())


if __name__ == "__main__":
    unittest.main()
