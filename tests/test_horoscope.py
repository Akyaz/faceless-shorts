"""Haftalık burç: gökyüzü hesabı, plan ve saat eşleşmesi (pipeline/horoscope.py)."""
import datetime
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from pipeline import horoscope, slots

MONDAY = datetime.datetime(2026, 11, 9, 8, tzinfo=horoscope.TURKEY)


class Sky(unittest.TestCase):
    def test_week(self):
        start = horoscope.week_start(MONDAY + datetime.timedelta(days=3))  # perşembe de aynı haftayı verir
        self.assertEqual(start, datetime.date(2026, 11, 9))
        self.assertEqual(horoscope.range_text(start), "9-15 Kasım")
        self.assertEqual(horoscope.range_text(datetime.date(2026, 11, 30)), "30 Kasım - 6 Aralık")

    def test_events_of_9_november_2026(self):
        heavens = horoscope.sky(datetime.date(2026, 11, 9))
        self.assertIn("Pazartesi 9 Kasım: Yeniay Akrep burcunda", heavens["events"])
        self.assertIn("Cuma 13 Kasım: Merkür geri hareketini bitiriyor", heavens["events"])
        self.assertIn("Güneş Akrep burcunda", heavens["positions"])
        self.assertEqual(len(heavens["moon"]), 7)

    def test_sign_boundaries(self):
        self.assertEqual(horoscope.sign_of(0.1), "Koç")
        self.assertEqual(horoscope.sign_of(359.9), "Balık")


class Plan(unittest.TestCase):
    def reply(self, names):
        return json.dumps({"intro": "9 Kasım'da Akrep'te yeniay var", "outro": "Senin burcun hangisi? Yorumlara yaz.",
                           "signs": [{"name": n, "text": f"{n} için Cuma günü iş planı yap"} for n in names]})

    def test_part_two(self):
        names = ["Aslan", "Başak", "Terazi", "Akrep"]
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), \
                mock.patch("pipeline.script._generate", return_value=self.reply(names)) as gen:
            plan = horoscope.plan(2, MONDAY)
        self.assertEqual(plan["title"], "Aslan, Başak, Terazi, Akrep Haftalık Burç Yorumu (9-15 Kasım)")
        items = [s for s in plan["segments"] if s["kind"] == "item"]
        self.assertEqual(items[0]["heading"], "Aslan")
        self.assertEqual(items[3]["label"], "4/4 · 23 EKİM - 21 KASIM")
        self.assertTrue(all(s["image_files"] for s in plan["segments"]))
        self.assertIn("Yeniay Akrep burcunda", gen.call_args[0][0])  # gökyüzü olayları isteme giriyor

    def test_missing_sign_fails(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), \
                mock.patch("pipeline.script._generate", return_value=self.reply(["Koç", "Boğa"])):
            with self.assertRaises(RuntimeError):
                horoscope.plan(1, MONDAY)


class Schedule(unittest.TestCase):
    def test_workflow_crons_match_slots(self):
        # Saat-tür eşleşmesi slots.py'de, tetikleme satırları iş akışında: biri değişip diğeri unutulmasın
        crons = set()
        for name in ("make-short.yml", "longform.yml", "weekly.yml"):
            text = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / name).read_text()
            crons |= set(re.findall(r'- cron: "([^"]+)"', text))
        self.assertEqual(crons, set(slots.SLOTS))

    def test_horoscope_slot_time(self):
        self.assertEqual(slots.slot_time("pazartesi 08:30", datetime.date(2026, 11, 9)).minute, 30)


if __name__ == "__main__":
    unittest.main()
