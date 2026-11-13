"""Dijital platform videoları (pipeline/platforms.py) ve bilgi serilerinin sırası (pipeline/evergreen.py)."""
import os
import unittest
from unittest import mock

from pipeline import evergreen, platforms, slots

TSV = ("country_name\tcountry_iso2\tweek\tcategory\tweekly_rank\tshow_title\tseason_title\tcumulative_weeks_in_top_10\n"
       "Turkey\tTR\t2026-11-01\tTV\t1\tEski\tN/A\t3\n"
       "Turkey\tTR\t2026-11-08\tFilms\t1\tCollision Course\tN/A\t2\n"
       "Turkey\tTR\t2026-11-08\tTV\t2\tA Couple of Lies\tA Couple of Lies: Limited Series\t2\n"
       "Turkey\tTR\t2026-11-08\tTV\t1\tMoney Trap\tMoney Trap: The Karun Treasure\t4\n"
       "Argentina\tAR\t2026-11-08\tTV\t1\tBaşka\tN/A\t1\n")


class Top10(unittest.TestCase):
    def test_latest_week_of_country_series_first(self):
        rows = platforms.netflix_top10(raw=TSV)
        self.assertEqual([r["title"] for r in rows], ["Money Trap", "A Couple of Lies", "Collision Course"])
        self.assertEqual(rows[0]["weeks"], 4)
        self.assertIn("1. sıra, listede 4. haftası", platforms.top10_note(rows[0]))


class Posters(unittest.TestCase):
    def test_infobox_image(self):
        text = "{{Bilgi kutusu dizi\n| ad = Bir Başkadır\n| görsel = Bir Başkadır afişi.jpg\n| tür = Dram\n}}"
        self.assertEqual(platforms.INFOBOX_IMAGE.search(text).group(1).strip(), "Bir Başkadır afişi.jpg")

    def test_without_tmdb_key_wikipedia_poster(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("pipeline.platforms.news_images", return_value=[{"url": "n"}]), \
                mock.patch("pipeline.platforms.vet_images", side_effect=lambda w, c: c), \
                mock.patch("pipeline.platforms.wiki_poster", return_value=[{"url": "u"}]) as wiki:
            # Önce haberlerden elenmiş yapım kareleri, afiş en sonda
            self.assertEqual(platforms.work_images({"title": "Bir Başkadır", "type": "tv"}), [{"url": "n"}, {"url": "u"}])
        wiki.assert_called_once()

    def test_no_work_no_images(self):
        self.assertEqual(platforms.work_images(None), [])


class Series(unittest.TestCase):
    def test_categories_rotate(self):
        rows = evergreen.topics()
        done = [{"topic": rows[0][1]}]  # eski kayıtlar kategorisiz: "bilgi" sayılır
        seen = []
        for _ in range(5):
            category, tr, _ = evergreen.next_topic(rows, done)
            seen.append(category)
            done.append({"topic": tr, "category": category})
        self.assertEqual(sorted(seen), sorted(evergreen.CATEGORIES))
        self.assertEqual(seen[-1], "bilgi")  # en son bilgi videosu çıkmıştı

    def test_every_category_has_topics(self):
        cats = {r[0] for r in evergreen.topics()}
        self.assertEqual(cats, set(evergreen.CATEGORIES))


class Slot(unittest.TestCase):
    def test_ten_oclock_is_platform(self):
        self.assertEqual(slots.SLOTS["50 6 * * *"], ("10:00", "platform"))


if __name__ == "__main__":
    unittest.main()


class LeadImage(unittest.TestCase):
    def test_og_image_and_size_param(self):
        from unittest import mock
        from pipeline import articles
        page = ('<meta property="og:image" content="https://cdn.site.com/logo.png">'
                '<meta name="twitter:image" content="https://cdn.site.com/a/karun.jpg?w=127&amp;q=80">')
        with mock.patch.object(articles, "resolve", lambda l: "https://www.site.com/haber"), \
                mock.patch.object(articles, "_get", lambda u: page):
            self.assertEqual(articles.lead_image("x"), ("https://cdn.site.com/a/karun.jpg?q=80", "site.com"))


class VetImages(unittest.TestCase):
    def test_keeps_only_picked(self):
        from unittest import mock
        from pipeline import platforms, script
        cands = [{"url": "a"}, {"url": "b"}, {"url": "c"}]
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "x"}), \
                mock.patch.object(platforms, "_jpeg", lambda u: b"j"), \
                mock.patch.object(script, "_generate", lambda *a, **k: '{"pick": [3, 1]}'):
            self.assertEqual(platforms.vet_images({"title": "T"}, cands), [{"url": "c"}, {"url": "a"}])

    def test_no_model_no_images(self):
        from unittest import mock
        from pipeline import platforms
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(platforms.vet_images({"title": "T"}, [{"url": "a"}]), [])
