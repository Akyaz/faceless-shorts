"""Saat kararı: hangi tetikleme video üretir, hangisi atlanır (pipeline/slots.py)."""
import datetime
import unittest

from pipeline import slots

UTC = datetime.timezone.utc
DAY = datetime.date(2026, 11, 4)


def at(text):
    return datetime.datetime.fromisoformat(text).replace(tzinfo=UTC)


class Done(unittest.TestCase):
    def entry(self, **kw):
        return {"slot": "10:00", "time": "2026-11-04T07:05:00Z", "status": "success", "videos": [{"url": "u"}], **kw}

    def test_successful_video_counts(self):
        self.assertTrue(slots.is_done([self.entry()], "10:00", DAY))

    def test_failed_without_video_is_retried(self):
        # Gemini 503 ile düşen çalışma: yedek tetikleme yeniden denemeli
        self.assertFalse(slots.is_done([self.entry(status="failure", videos=[])], "10:00", DAY))

    def test_failed_upload_counts(self):
        # Video üretildi ama yüklenemedi: yeniden üretilmez, panelden yeniden yüklenir
        self.assertTrue(slots.is_done([self.entry(status="failure", videos=[{"url": None}])], "10:00", DAY))

    def test_other_slot_or_day_does_not_count(self):
        self.assertFalse(slots.is_done([self.entry(slot="12:00")], "10:00", DAY))
        self.assertFalse(slots.is_done([self.entry(time="2026-11-03T07:05:00Z")], "10:00", DAY))

    def test_day_is_turkish(self):
        # 00:30 Türkiye saati bir önceki gün UTC'dir
        self.assertTrue(slots.is_done([self.entry(time="2026-11-03T21:30:00Z")], "10:00", DAY))


class Stale(unittest.TestCase):
    def test_on_time_schedule(self):
        # 10:00 saatinin 06:50 UTC (09:50 TSİ) tetiklemesi
        self.assertEqual(slots.stale("schedule", "10:00", at("2026-11-04T06:50:00"), at("2026-11-04T06:51:00")), "")

    def test_schedule_started_hours_late(self):
        # Dün: 10:00 videosu 17:45'te çıktı
        self.assertIn("sonra", slots.stale("schedule", "10:00", at("2026-11-04T14:30:00"), at("2026-11-04T14:31:00")))

    def test_queued_overnight(self):
        # 4 Kasım 23:51 UTC'de tetiklenip 12 saat kuyrukta bekleyen 21:00 tarih videosu
        self.assertIn("kuyrukta", slots.stale("schedule", "21:00", at("2026-11-04T23:51:00"), at("2026-11-05T11:28:00")))

    def test_manual_late_slot_allowed(self):
        # Panelden kaçan saati sonradan üretmek serbest
        self.assertEqual(slots.stale("workflow_dispatch", "10:00", at("2026-11-04T14:00:00"), at("2026-11-04T14:01:00")), "")

    def test_weekly_slot_name(self):
        self.assertEqual(slots.slot_time("pazar 11:00", DAY).hour, 11)


if __name__ == "__main__":
    unittest.main()
