"""Metin denetimi: eksik bilgi haber metinlerinden tamamlanır, bulunamazsa haber atlanır (pipeline/review.py)."""
import json
import os
import unittest
from unittest import mock

from pipeline import review

SOURCE = {"title": "İstanbul'da 5 ilçede su kesintisi", "source": "Haber", "related": []}
ARTICLE = [{"source": "İSKİ", "title": "Su kesintisi", "text": "Kadıköy, Üsküdar, Ataşehir, Maltepe ve Kartal..."}]
_patches = [mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}),
            mock.patch("pipeline.articles.texts", return_value=ARTICLE)]


def setUpModule():
    for p in _patches:
        p.start()


def tearDownModule():
    for p in _patches:
        p.stop()


def story():
    texts = ["Yarın musluklar kuruyabilir.", "İstanbul'da 5 ilçede su kesilecek.", "Sence önlem yeterli mi?"]
    return {"title": "5 ilçede su kesintisi", "hook_title": "Su kesintisi", "lang": "tr", "sources": [SOURCE],
            "segments": [{"kind": "story", "source": "Haber", "text": t} for t in texts], "pronounce": {}}


def digest():
    items = [{"kind": "item", "label": f"GÜNÜN ÖZETİ {i}/3", "heading": f"Başlık {i}", "text": f"Madde {i}.",
              "headline": {"title": f"Haber {i}", "source": "X"}} for i in (1, 2, 3)]
    return {"title": "Günün üç haberi", "lang": "tr", "sources": [i["headline"] for i in items],
            "segments": [{"kind": "intro", "text": "Bugünün üç haberi, bir dakikada."}] + items
                        + [{"kind": "outro", "text": "Sence hangisi önemli?"}]}


def reply(out):
    return {"content": {"parts": [{"text": json.dumps(out, ensure_ascii=False)}]}}


class Story(unittest.TestCase):
    def run_check(self, out):
        with mock.patch("pipeline.script._call", return_value=reply(out)):
            return review.check_story(story())

    def test_fills_missing_districts(self):
        fixed = ["Yarın musluklar kuruyabilir.", "Kadıköy, Üsküdar, Ataşehir, Maltepe ve Kartal'da su kesilecek.",
                 "Sence önlem yeterli mi?"]
        plan = self.run_check({"status": "fixed", "questions": ["Hangi ilçeler?"], "paragraphs": fixed})
        self.assertIn("Kadıköy", plan["segments"][1]["text"])
        self.assertEqual(plan["segments"][1]["source"], "Haber")  # diğer alanlar korunur

    def test_ok_keeps_text(self):
        self.assertEqual(self.run_check({"status": "ok"}), story())

    def test_unfixable_raises(self):
        with self.assertRaises(review.Incomplete):
            self.run_check({"status": "unfixable", "questions": ["Hangi ilçeler?"]})

    def test_ok_with_hollow_paragraph_is_rejected(self):
        # 5 Kasım denemesi: "kaynak ayırdıklarını duyurdu" (ne kadar?) varken denetçi "ok" demişti
        with self.assertRaises(review.Incomplete):
            self.run_check({"status": "ok", "checks": [{"n": 2, "concrete": False, "missing": "ne kadar?"}]})

    def test_prompt_contains_article_text(self):
        with mock.patch("pipeline.script._call", return_value=reply({"status": "ok"})) as call:
            review.check_story(story())
        self.assertIn("Kadıköy, Üsküdar", call.call_args[0][0]["contents"][0]["parts"][0]["text"])

    def test_structure_change_is_rejected(self):
        with self.assertRaises(review.Incomplete):
            self.run_check({"status": "fixed", "paragraphs": ["tek paragraf"]})


class Digest(unittest.TestCase):
    def test_drops_unfixable_item_and_recounts(self):
        out = {"items": [{"n": 1, "status": "ok"}, {"n": 2, "status": "unfixable", "questions": ["Neden?"]},
                         {"n": 3, "status": "fixed", "text": "Madde üç, nedeniyle birlikte"}]}
        with mock.patch("pipeline.script._call", return_value=reply(out)):
            plan = review.check_digest(digest())
        items = [s for s in plan["segments"] if s["kind"] == "item"]
        self.assertEqual([s["text"] for s in items], ["Madde 1.", "Madde üç, nedeniyle birlikte."])
        self.assertEqual([s["label"] for s in items], ["GÜNÜN ÖZETİ 1/2", "GÜNÜN ÖZETİ 2/2"])
        self.assertEqual(plan["segments"][0]["text"], "Bugünün iki haberi, bir dakikada.")
        self.assertEqual(plan["title"], "Günün iki haberi")
        self.assertEqual(len(plan["sources"]), 2)


class Check(unittest.TestCase):
    def test_service_failure_keeps_text(self):
        # Gemini yanıt vermezse saat boşa gitmesin: metin denetimsiz kullanılır
        with mock.patch("pipeline.script._call", side_effect=RuntimeError("503")):
            self.assertEqual(review.check(story(), True), story())

    def test_no_article_keeps_text(self):
        # Siteler engellerse ya da Google News biçimi değişirse saat boşa gitmesin
        with mock.patch("pipeline.articles.texts", return_value=[]), mock.patch("pipeline.script._call") as call:
            self.assertEqual(review.check(story(), True), story())
        call.assert_not_called()

    def test_incomplete_is_not_swallowed(self):
        with mock.patch("pipeline.script._call", return_value=reply({"status": "unfixable"})):
            with self.assertRaises(review.Incomplete):
                review.check(story(), True)


class Quota(unittest.TestCase):
    def test_search_quota_does_not_block_plain_calls(self):
        # 5 Kasım: aramalı istekte 429, aynı çalışmanın görsel seçimini de durdurmuştu
        import io
        import urllib.error
        from pipeline import script
        script._out_of_quota.clear()
        calls = []

        def fake(req, timeout=None):
            searching = b"google_search" in req.data
            calls.append(searching)
            if searching:
                raise urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b"quota"))
            return io.BytesIO(json.dumps({"candidates": [reply({"ok": 1})]}).encode())

        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            with self.assertRaises(RuntimeError):
                script._call({"tools": [{"google_search": {}}]}, "k", "m1")
            self.assertEqual(json.loads(script._call({}, "k", "m1")["content"]["parts"][0]["text"]), {"ok": 1})
        script._out_of_quota.clear()


if __name__ == "__main__":
    unittest.main()
