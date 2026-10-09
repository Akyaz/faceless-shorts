"""Edge TTS ile Türkçe seslendirme ve kelime zamanlamaları."""
import asyncio

import edge_tts

VOICE = "tr-TR-AhmetNeural"
RATE = "+8%"


async def _synthesize(text, out_path, voice):
    try:
        comm = edge_tts.Communicate(text, voice, rate=RATE, boundary="WordBoundary")
    except TypeError:  # eski sürümler kelime sınırını varsayılan gönderir
        comm = edge_tts.Communicate(text, voice, rate=RATE)
    words = []
    with open(out_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"text": chunk["text"], "start": start,
                              "end": start + chunk["duration"] / 1e7})
    return words


def synthesize(text, out_path, voice=VOICE):
    """Sesi out_path'e yazar, [{text, start, end}] kelime listesini döner (saniye)."""
    return asyncio.run(_synthesize(text, out_path, voice))
