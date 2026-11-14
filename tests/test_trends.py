"""Google Trends Türkiye ile konu seçimi ve yeni takvim (15 Kasım 2026 ölçümü)."""
import unittest

from pipeline import slots, trends

XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item><title>gönül dağı</title><ht:approx_traffic>500+</ht:approx_traffic>
 <ht:news_item><ht:news_item_title>Gönül Dağı bu akşam var mı?</ht:news_item_title>
  <ht:news_item_url>https://a/1</ht:news_item_url><ht:news_item_source>Gazete Arena</ht:news_item_source></ht:news_item>
 <ht:news_item><ht:news_item_title>Gönül Dağı yeni bölüm</ht:news_item_title>
  <ht:news_item_url>https://a/2</ht:news_item_url><ht:news_item_source>Diziler.com</ht:news_item_source></ht:news_item>
</item>
<item><title>tev burs sonuçları</title><ht:approx_traffic>5,000+</ht:approx_traffic>
 <ht:news_item><ht:news_item_title>TEV burs sonuçları açıklandı</ht:news_item_title>
  <ht:news_item_url>https://b/1</ht:news_item_url><ht:news_item_source>Hürriyet</ht:news_item_source></ht:news_item>
</item>
<item><title>haberi yok</title><ht:approx_traffic>900+</ht:approx_traffic></item>
</channel></rss>"""


class Parse(unittest.TestCase):
    def test_sorted_by_traffic_and_needs_news(self):
        items = trends.parse(XML)
        self.assertEqual([t["query"] for t in items], ["tev burs sonuçları", "gönül dağı"])
        self.assertEqual(items[0]["traffic"], 5000)

    def test_headlines_carry_search_note(self):
        heads = trends.headlines(trends.parse(XML))
        self.assertEqual(heads[0]["title"], "TEV burs sonuçları açıklandı")
        self.assertIn("5000+ arama", heads[0]["related"][-1]["title"])
        self.assertEqual(len(heads[1]["related"]), 2)  # diğer haber + arama bilgisi: "yeterli kaynak" sayılır

    def test_boost_moves_searched_topic_first(self):
        heads = [{"title": "Kızılcık Şerbeti final", "related": []}, {"title": "Gönül Dağı yeni sezon", "related": []}]
        out = trends.boost(heads, trends.parse(XML))
        self.assertEqual(out[0]["title"], "Gönül Dağı yeni sezon")
        self.assertEqual(out[0]["related"][-1]["source"], "Google Trends")
        self.assertEqual(trends.boost(heads, []), heads)


class Freshness(unittest.TestCase):
    def test_old_searches_dropped(self):
        import datetime
        xml = XML.replace("<title>gönül dağı</title>", "<title>gönül dağı</title><pubDate>Sat, 14 Nov 2026 00:00:00 -0800</pubDate>")
        now = datetime.datetime(2026, 11, 15, 1, 30, tzinfo=datetime.timezone.utc) - datetime.timedelta(hours=3)
        self.assertEqual([t["query"] for t in trends.parse(xml, now)], ["tev burs sonuçları"])  # 14,5 saat önce


class Schedule(unittest.TestCase):
    def test_longform_and_weekly_off_story_at_nine(self):
        modes = {name: mode for name, mode in slots.SLOTS.values()}
        self.assertEqual(modes["21:00"], "story")
        self.assertNotIn("longform", modes.values())
        self.assertNotIn("weekly", modes.values())

    def test_crons_match_workflow(self):
        import pathlib, re
        text = pathlib.Path(__file__).resolve().parent.parent.joinpath(".github/workflows/make-short.yml").read_text()
        crons = set(re.findall(r'cron: "([^"]+)"', text))
        for cron, (_, mode) in slots.SLOTS.items():
            self.assertIn(cron, crons, f"{cron} ({mode}) make-short.yml'de yok")


if __name__ == "__main__":
    unittest.main()
