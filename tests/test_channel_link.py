"""Açıklamadaki kanal bağlantısı kanal kimliğiyle; Instagram "@" adresini kendi profili sanıyordu (18 Kasım 2026)."""
import unittest

from pipeline import instagram, render

SUB = "https://www.youtube.com/channel/UC-FK-qTfj7X78lDNnvJZvAw?sub_confirmation=1"


class ChannelLink(unittest.TestCase):
    def test_youtube_line_opens_subscribe(self):
        self.assertEqual(render.channel_line(), f"Abone ol: {SUB}")
        self.assertNotIn("sub_confirmation", render.channel_line(subscribe=False))  # acı haberde abone çağrısı yok

    def test_reels_caption_keeps_subscribe_link(self):
        meta = {"description": f"Başlık\n\n{render.channel_line()}\n\nMetin.\n\nKanala abone ol.\n\n#shorts"}
        text = instagram.caption(meta)
        self.assertIn(SUB, text)
        self.assertNotIn("Kanala abone ol.", text)

    def test_old_video_gets_link_instead_of_at_address(self):
        meta = {"description": "Başlık\n\nAbone ol: https://www.youtube.com/@QuickRecapChannel?sub_confirmation=1\n\nMetin."}
        text = instagram.caption(meta)
        self.assertIn(SUB, text)
        self.assertNotIn("@QuickRecapChannel", text)


if __name__ == "__main__":
    unittest.main()
