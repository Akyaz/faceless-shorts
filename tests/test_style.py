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


if __name__ == "__main__":
    unittest.main()
