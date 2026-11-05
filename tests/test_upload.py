"""YouTube yüklemesi yarıda kalınca kaldığı yerden devam eder, videoyu ikinci kez oluşturmaz (pipeline/upload.py)."""
import email.message
import io
import json
import unittest
import urllib.error
from unittest import mock

from pipeline import upload


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, headers=None):
    msg = email.message.Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("u", code, "x", msg, io.BytesIO(b""))


class Send(unittest.TestCase):
    def run_send(self, responses):
        calls = []

        def fake(req, timeout=None):
            calls.append((req.get_method(), dict(req.header_items()), len(req.data or b"")))
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return Response(json.dumps(result).encode())

        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            return upload._send("https://session", "t", b"x" * 100), calls

    def test_resumes_from_received_bytes(self):
        video, calls = self.run_send([
            urllib.error.URLError("koptu"),
            http_error(308, {"Range": "bytes=0-59"}),
            {"id": "abc"},
        ])
        self.assertEqual(video["id"], "abc")
        self.assertEqual(calls[2][1]["Content-range"], "bytes 60-99/100")
        self.assertEqual(calls[2][2], 40)

    def test_completed_upload_is_not_sent_again(self):
        # Yanıt kayboldu ama video YouTube'a ulaşmıştı: ikinci video çıkmamalı
        video, calls = self.run_send([TimeoutError(), {"id": "abc"}])
        self.assertEqual(video["id"], "abc")
        self.assertEqual(len(calls), 2)

    def test_quota_error_is_not_retried(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.run_send([http_error(403)])


if __name__ == "__main__":
    unittest.main()
