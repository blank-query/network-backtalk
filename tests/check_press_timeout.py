# Run: .venv/bin/python tests/check_press_timeout.py
# Self-check: a press whose audio stops (a client that died mid-press), or
# that runs past its cap, ends by itself as nothing heard, and the client is
# told so with an "endpoint", instead of holding the voice line forever.
import asyncio, json, os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk import web
from backtalk.web import BrowserBridge, Conn

END = {"type": "endpoint", "speech": False}
FRAME = struct.pack("<I", 16000) + b"\0\0" * 320


class WS:
    def __init__(s): s.sent = []
    async def send(s, data): s.sent.append(json.loads(data))


async def main():
    web.NO_AUDIO_S = 0.3
    b = BrowserBridge({})
    conn = Conn(WS(), b)
    b._on_press(conn)
    conn._frames.put_nowait(FRAME)          # some audio, then nothing
    assert await b.record_until_release(conn) is None
    await asyncio.sleep(0)
    assert conn.ws.sent == [END] and not conn.recording, conn.ws.sent

    b._on_press(conn)                        # audio that never stops
    async def feed():
        while True:
            conn._frames.put_nowait(FRAME); await asyncio.sleep(0.05)
    f = asyncio.ensure_future(feed())
    assert await b.record_until_release(conn, max_s=0.6) is None
    f.cancel(); await asyncio.sleep(0)
    assert conn.ws.sent == [END, END] and not conn.recording, conn.ws.sent
    print("press timeout ok: a silent or endless press ends as nothing heard")

asyncio.run(main())
