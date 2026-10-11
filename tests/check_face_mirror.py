# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_face_mirror.py
# Self-check: a remote device's turn shows, as text only, in this machine's
# face terminal. The face (a loopback hello with no "model") gets the
# phone's "line" frames and none of its audio or other frames; a broadcast
# reaches the face once, not twice; the face's own lines go nowhere else;
# a phone on loopback (a relayed app says "model") is no face. Run against
# each instance's own "web" settings (Jarvis, Friday), on spare ports.
import asyncio, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import websockets
from backtalk.web import BrowserBridge


async def frames(ws, t=0.4):
    """What arrived, minus the bridge's own pushes (tasks, state)."""
    out = []
    try:
        while True:
            m = await asyncio.wait_for(ws.recv(), t)
            if isinstance(m, bytes) or json.loads(m)["type"] not in ("tasks", "state"):
                out.append(m)
    except asyncio.TimeoutError:
        return out


async def check(cfg_file, port):
    with open(cfg_file) as f:
        cfg = json.load(f).get("web", {})
    br = BrowserBridge(cfg | {"host": "127.0.0.1", "port": port})
    asyncio.ensure_future(br.serve())
    await asyncio.sleep(0.3)
    url = f"ws://127.0.0.1:{port}"
    async with websockets.connect(url) as face, websockets.connect(url) as phone:
        await face.send(json.dumps({"type": "hello", "device_id": "face"}))
        await phone.send(json.dumps({"type": "hello", "device_id": "pix", "model": "Pixel 8 Pro"}))
        await asyncio.sleep(0.3)
        await frames(face); await frames(phone)
        by = {c.id: c for c in br._conns}
        assert by["face"].face and not by["pix"].face, by

        s = br.make_sink(by["pix"])
        s.send({"type": "line", "who": "you", "text": "hello"})
        s(24000, np.ones(240, dtype=np.int16))
        s.send({"type": "line", "who": "jarvis", "text": "Good evening, sir."})
        s.reply_done()
        got = await frames(face)
        assert all(isinstance(m, str) for m in got), "audio reached the face"
        assert [json.loads(m) for m in got] == [
            {"type": "line", "who": "you", "text": "hello"},
            {"type": "line", "who": "jarvis", "text": "Good evening, sir."}], got
        assert [m["text"] for m in br._lines["face"]] == ["hello", "Good evening, sir."]
        p = await frames(phone)
        assert sum(isinstance(m, bytes) for m in p) == 1 and len(p) == 4, p

        br.make_broadcast_sink().send({"type": "line", "who": "jarvis", "text": "report"})
        assert len(await frames(face)) == 1 and len(await frames(phone)) == 1

        br.make_sink(by["face"]).send({"type": "line", "who": "you", "text": "typed here"})
        assert len(await frames(face)) == 1 and await frames(phone) == []
    await br.stop()
    print("ok", cfg_file)


async def main():
    here = os.path.join(os.path.dirname(__file__), "..")
    await check(os.path.join(here, "backtalk.json"), 18798)
    friday = "/home/rigs/projects/Friday/backtalk.json"
    if os.path.exists(friday):
        await check(friday, 18799)


asyncio.run(main())
