"""Açılış ve kapanış kuralı: bilgi vermeyen açılış ve genel kapanış sorusu yakalanır (pipeline/script.py)."""
import unittest

from pipeline import script


class WeakEnding(unittest.TestCase):
    def test_question_opening(self):
        # Kanalın en az izlenen haberlerinden (11 izlenme)
        self.assertTrue(script.weak_ending(["Ocak ayında alacağın yeni maaşını şimdiden merak ediyor musun?", "x."]))

    def test_rhetorical_opening_without_question_mark(self):
        self.assertTrue(script.weak_ending(["Bunu biliyor musun, kış erken geliyor.", "x."]))

    def test_generic_closing_question(self):
        self.assertEqual(script.weak_ending(["Emekliye yüzde 12 zam.", "Sence bu ne anlama geliyor?"]),
                         ["Sence bu ne anlama geliyor?"])

    def test_plain_story_passes(self):
        self.assertEqual(script.weak_ending(["İstanbul'da yarın okullar tatil. Valilik duyurdu.",
                                             "Okullar perşembe yeniden açılıyor."]), [])

    def test_named_choice_question_passes(self):
        self.assertEqual(script.weak_ending(["Fenerbahçe'de hoca arayışı sürüyor.", "Montella mı, yerli hoca mı?"]), [])



class Length(unittest.TestCase):
    def test_short_script_is_flagged(self):
        # 12 Kasım denemesi: 2 paragraf, 30 kelime, hangi maç olduğu yok
        self.assertTrue(script.style_problems(["Arda Güler 30 metreden harika bir gol attı.", "De Bruyne övdü."]))

    def test_normal_script_passes(self):
        para = "Bu cümle tam on beş kelimeden oluşan ve haberi anlatan sade bir örnek cümledir burada."
        self.assertEqual(script.style_problems([para, para, para, "Okullar perşembe yeniden açılıyor."]), [])


if __name__ == "__main__":
    unittest.main()
