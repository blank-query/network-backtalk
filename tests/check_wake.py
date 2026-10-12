# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_wake.py
# Self-check: the Kitchen wake word trial and private device answers. A
# devices.json "wake" entry reaches that device on hello (and only that
# one); a wake-opened tap is flagged on the connection, a plain press
# clears it; "stop listening" mutes a wake device's word, "start
# listening" unmutes it; words after the wake word count as name-led; a
# private answer (notifications read back) never lands in the log.
import asyncio, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import websockets
from backtalk import device
from backtalk.main import wake_mute, wake_text, NAME
from backtalk.web import BrowserBridge

assert wake_mute("micmute", "on") is True and wake_mute("micmute", "quiet") is True
assert wake_mute("micopen", "muted") is False
assert wake_mute("micmute", None) is None and wake_mute("micopen", "on") is None
assert wake_text("stop listening") == f"{NAME}, stop listening"
assert wake_text(f"{NAME}, stop listening") == f"{NAME}, stop listening"
assert wake_text("what's the time") == "what's the time"

D = tempfile.mkdtemp()
LOG = os.environ.get("BACKTALK_LOG", "")


async def recv(ws, kind, t=3):
    while True:
        m = await asyncio.wait_for(ws.recv(), t)
        if isinstance(m, str) and json.loads(m).get("type") == kind:
            return json.loads(m)


async def main():
    br = BrowserBridge({"host": "127.0.0.1", "port": 18798})
    br._token = "peer-secret"
    br.devices_file = os.path.join(D, "devices.json")
    with open(br.devices_file, "w") as f:
        json.dump({"k": {"name": "Kitchen", "role": "shared", "wake": True},
                   "p": {"name": "Phone", "role": "full"}}, f)
    srv = asyncio.ensure_future(br.serve())
    await asyncio.sleep(0.3)
    url = "ws://127.0.0.1:18798"
    caps = {"role": "full", "actions": ["notifications"]}
    async with websockets.connect(url) as k, websockets.connect(url) as p:
        await k.send(json.dumps({"type": "hello", "device_id": "k", "model": "Display"}))
        assert (await recv(k, "wake"))["cfg"] == {"on": True}
        await p.send(json.dumps({"type": "hello", "device_id": "p", "model": "Phone", "caps": caps}))
        await recv(p, "role")
        try:
            await recv(p, "wake", 0.5)
            raise AssertionError("a device without a wake entry got one")
        except asyncio.TimeoutError:
            pass
        await k.send(json.dumps({"type": "press"}))
        await k.send(json.dumps({"type": "latch", "wake": True}))
        await asyncio.sleep(0.2)
        conn = next(c for c in br._conns if c.id == "k")
        assert conn.wake and conn.latched
        await k.send(json.dumps({"type": "release"}))
        await k.send(json.dumps({"type": "press"}))
        await asyncio.sleep(0.2)
        assert not conn.wake, "a plain press is not a wake tap"

        async def device_side():
            m = await recv(p, "phone")
            await p.send(json.dumps({"type": "phone_result", "id": m["id"], "private": True,
                                     "text": "#1 Messages, from Sam: secret words"}))
        side = asyncio.ensure_future(device_side())
        r = await device.ask(url, "peer-secret", "Pi Jarvis",
                             {"type": "device", "device": "Phone", "frame": {"do": "notifications", "n": 3}})
        await side
        assert r["ok"] and "secret words" in r["text"], r
        r = await device.ask(url, "peer-secret", "Pi Jarvis",
                             {"type": "device", "device": "Garage", "frame": {"do": "ring"}})
        assert not r["ok"], r
    srv.cancel()
    if LOG and os.path.exists(LOG):
        log = open(LOG).read()
        assert "secret words" not in log and "chars, private" in log, "a private answer was logged"
    print("OK")

asyncio.run(main())
