# Run: .venv/bin/python tests/check_press_end.py
# Self-check: a press the voice line won't record (this tab is already
# recording) or cuts off (a mode switch) is ended at the client with an
# "endpoint", so the face never sits on a live press with its reply paused.
import asyncio, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk.web import BrowserBridge, Conn


class WS:
    def __init__(s): s.sent = []
    async def send(s, data): s.sent.append(json.loads(data))


async def main():
    b = BrowserBridge({})
    conn = Conn(WS(), b)
    b._on_press(conn)                    # recording
    b._on_press(conn)                    # a second press while it records
    await asyncio.sleep(0)
    assert conn.ws.sent == [{"type": "endpoint", "speech": False}], conn.ws.sent
    assert await b.record_until_release(conn, abort=lambda: True) is None
    await asyncio.sleep(0)
    assert conn.ws.sent[1:] == [{"type": "endpoint", "speech": False}], conn.ws.sent
    assert not conn.recording
    print("press end ok: an ignored or aborted press is ended at the client")

asyncio.run(main())
