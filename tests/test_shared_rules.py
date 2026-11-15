"""Bütün türler aynı kapanış ve metin denetiminden geçer (kural temizliği 3. adım, 15 Kasım 2026)."""
import json
import unittest
from unittest import mock

from pipeline import script, weekly


def _digest_reply(outro, intro="Bugünün üç haberi."):
    items = [{"pick": i, "heading": f"Başlık {i}", "text": f"Haber {i} somut bilgisiyle anlatıldı."}
             for i in (1, 2, 3)]
    return json.dumps({"intro": intro, "items": items, "outro": outro, "title": "Özet", "hashtags": []})


HEADLINES = [{"title": f"Haber {i}", "source": "Kaynak", "link": f"https://x/{i}"} for i in (1, 2, 3)]


class SharedRules(unittest.TestCase):
    def test_generic_which_question_flagged(self):
        opening = "Fenerbahçe yeni hocasını arıyor."
        self.assertTrue(script.weak_ending([opening, "Sence günün en önemli haberi hangisiydi?"]))
        self.assertTrue(script.weak_ending([opening, "Which one surprised you most?"]))
        self.assertFalse(script.weak_ending([opening, "Montella mı, yerli hoca mı?"]))

    def test_sentence_problems_catch_comment_call(self):
        self.assertTrue(script.sentence_problems(["Senin burcun hangisi? Yorumlara yaz."]))
        self.assertFalse(script.sentence_problems(["Okullar perşembe yeniden açılıyor."]))

    def _digest(self, reply):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch.object(script, "_generate", return_value=reply):
            return script.digest_script(HEADLINES, "morning")

    def test_digest_question_outro_dropped(self):
        plan = self._digest(_digest_reply("Bugün seni en çok hangisi etkileyecek?"))
        self.assertEqual(plan["segments"][-1]["kind"], "item")

    def test_digest_concrete_outro_kept(self):
        plan = self._digest(_digest_reply("Yeni fiyatlar gece yarısı geçerli"))
        self.assertEqual(plan["segments"][-1], {"kind": "outro", "text": "Yeni fiyatlar gece yarısı geçerli."})

    def test_digest_question_intro_replaced(self):
        plan = self._digest(_digest_reply("", intro="Bugün neler oldu biliyor musun?"))
        self.assertEqual(plan["segments"][0]["text"], script.DIGESTS["morning"]["fallback_intro"])

    def test_rewrite_keeps_hard_problem_out(self):
        bad = {"paragraphs": ["Kısa."]}
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch.object(script, "_generate", return_value=json.dumps(bad)):
            with self.assertRaises(script.TextRejected):
                script.rewritten("istem", bad, script.text_problems)

    def test_weekly_keeps_concrete_last_paragraph(self):
        texts = ["Okullar tatil edildi.", "Karar valilikten geldi.", "Okullar perşembe açılıyor."]
        plan = {"title": "Okullar", "hook_title": "Okullar Tatil",
                "sources": [{"title": "Okullar", "source": "Kaynak", "link": "https://x"}],
                "segments": [{"kind": "story", "text": t} for t in texts]}
        from datetime import date
        segments = weekly.build_segments([plan], date(2026, 11, 15))
        self.assertIn("Okullar perşembe açılıyor.", [s["text"] for s in segments])
        self.assertNotIn("Yorumlara yaz", segments[-1]["text"])


if __name__ == "__main__":
    unittest.main()
