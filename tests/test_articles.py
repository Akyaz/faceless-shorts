"""Haber metni çıkarma ve kümedeki yayın bağlantıları (pipeline/articles.py, pipeline/news.py)."""
import json
import unittest
from unittest import mock

from pipeline import articles, news

BODY = "İSKİ, yarın 09.00-17.00 arasında Kadıköy, Üsküdar ve Ataşehir'de su verilemeyeceğini açıkladı. " * 4


class Extract(unittest.TestCase):
    def test_structured_body_first(self):
        ld = json.dumps({"@graph": [{"@type": "NewsArticle", "articleBody": BODY}]})
        page = f'<script type="application/ld+json">{ld}</script><p>{"menü bağlantısı " * 10}</p>'
        self.assertTrue(articles.extract(page).startswith("İSKİ, yarın"))

    def test_paragraph_fallback_skips_short_and_scripts(self):
        page = f"<nav><p>{'Anasayfa Gündem Spor ' * 5}</p></nav><p>Kısa</p><p>{BODY}</p><script>var x = 1;</script>"
        self.assertEqual(articles.extract(page), BODY.strip())

    def test_texts_skips_blocked_site(self):
        headline = {"title": "a", "source": "A", "link": "l1", "related": [
            {"title": "b", "source": "B", "link": "l2"}, {"title": "c", "source": "C", "link": ""}]}
        with mock.patch("pipeline.articles.article_text", side_effect=["", BODY]):
            found = articles.texts(headline, count=2)
        self.assertEqual([a["source"] for a in found], ["B"])


class Related(unittest.TestCase):
    def test_keeps_links(self):
        desc = ('<ol><li><a href="https://news.google.com/rss/articles/X" target="_blank">Başlık</a>'
                '&nbsp;&nbsp;<font color="#6f6f6f">NTV</font></li></ol>')
        self.assertEqual(news._related(desc), [{"title": "Başlık", "source": "NTV",
                                                "link": "https://news.google.com/rss/articles/X"}])


if __name__ == "__main__":
    unittest.main()
