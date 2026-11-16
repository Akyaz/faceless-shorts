import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import longform


class Build(unittest.TestCase):
    def test_build_keeps_chapter_lines_and_writes_captions(self):
        # 14 Kasım 2026: altyazı listesi bölümün konuşma listesiyle aynı adı taşıyordu; döngü kendi ekledikleri
        # üstünden geçip düştü ve 15-16 Kasım'da uzun video çıkmadı
        script = {"lang": "tr", "topic": "Göbekli Tepe", "label": "Tarih", "title": "Başlık", "description": "Açıklama",
                  "speakers": {"A": {"name": "Elif", "voice": "female"}, "B": {"name": "Kerem", "voice": "male"}},
                  "sources": [{"title": "Kaynak", "url": "https://example.org"}],
                  "chapters": [{"heading": "Giriş", "lines": [{"s": "A", "t": "Bir."}, {"s": "B", "t": "İki."}]},
                               {"heading": "Bölüm", "lines": [{"s": "A", "t": "Üç."}]}]}
        words = [{"start": 0.0, "end": 1.0, "word": "x"}]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(longform, "speak_all", return_value=[words, words, words]), \
                mock.patch.object(longform.images, "find_backgrounds", return_value=[]), \
                mock.patch.object(longform.render, "draw_wide_card"), \
                mock.patch.object(longform.render, "audio_duration", return_value=1.0), \
                mock.patch.object(longform.render, "write_ass"), \
                mock.patch.object(longform.render, "render_segment"), \
                mock.patch.object(longform.render, "concat"), \
                mock.patch.object(longform.render, "add_subscribe"), \
                mock.patch.object(longform.render, "channel_line", return_value="Kanal"), \
                mock.patch.object(longform.music, "add", return_value="Müzik: x"), \
                mock.patch.object(longform, "_silence"), \
                mock.patch.object(longform.captions, "srt", side_effect=lambda timed: str(len(timed))) as srt:
            longform.build(script, Path(tmp))
            meta = json.loads((Path(tmp) / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["captions"], "3")
        self.assertEqual(len(script["chapters"][0]["lines"]), 2)  # metin dosyasının içeriği değişmez
        srt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
