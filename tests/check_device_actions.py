# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_device_actions.py
# Self-check: device actions as a tool and Pi-held timers. A device's
# hello caps land in devices.json and its role comes back to it; a peer's
# device frame reaches it as a numbered phone frame, and the answer with
# that id goes back to the peer (not into a turn), a phone_result without
# an id still starts a turn; a device with no caps, or not connected, is
# refused; the devices list. Timers: add, list, cancel, due.
import asyncio, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import websockets
from backtalk import timer as T, device
from backtalk.web import BrowserBridge

D = tempfile.mkdtemp()


async def recv(ws, kind, t=3):
    while True:
        m = await asyncio.wait_for(ws.recv(), t)
        if isinstance(m, str) and json.loads(m).get("type") == kind:
            return json.loads(m)


async def main():
    br = BrowserBridge({"host": "127.0.0.1", "port": 18797})
    br._token = "peer-secret"
    br.devices_file = os.path.join(D, "devices.json")
    with open(br.devices_file, "w") as f:
        json.dump({"pix": {"name": "Phone", "role": "full"}, "old": {"name": "Kitchen"}}, f)
    turns = []
    br.on_phone_result = lambda conn, text: turns.append(text)
    srv = asyncio.ensure_future(br.serve())
    await asyncio.sleep(0.3)
    url = "ws://127.0.0.1:18797"
    caps = {"role": "full", "actions": ["battery", "ring"]}
    async with websockets.connect(url) as pix, websockets.connect(url) as old:
        await pix.send(json.dumps({"type": "hello", "device_id": "pix", "model": "Phone", "caps": caps}))
        assert (await recv(pix, "role"))["role"] == "full"
        await old.send(json.dumps({"type": "hello", "device_id": "old"}))
        await asyncio.sleep(0.2)
        assert br.devices()["pix"]["caps"] == caps and "caps" not in br.devices()["old"]
        await old.send(json.dumps({"type": "caps", "caps": {"role": "shared", "actions": []}}))
        await asyncio.sleep(0.2)
        assert br.devices()["old"]["caps"]["role"] == "shared" and br.devices()["old"]["name"] == "Kitchen"

        # the tool, end to end: the CLI's ask() through the bridge to the device
        async def device_side():
            m = await recv(pix, "phone")
            assert m["do"] == "battery" and m["id"], m
            await pix.send(json.dumps({"type": "phone_result", "id": m["id"], "text": "81%, charging"}))
        side = asyncio.ensure_future(device_side())
        r = await device.ask(url, "peer-secret", "Pi Jarvis",
                             {"type": "device", "device": "phone", "frame": {"do": "battery"}})
        await side
        assert r == {"type": "device_result", "ok": True, "text": "81%, charging"}, r
        assert turns == [], "an answered id never starts a turn"
        r = await device.ask(url, "peer-secret", "Pi Jarvis",
                             {"type": "device", "device": "Kitchen", "frame": {"do": "ring"}})
        assert r["ok"] is False and "too old" in r["text"], r
        r = await device.ask(url, "peer-secret", "Pi Jarvis",
                             {"type": "device", "device": "Garage", "frame": {"do": "ring"}})
        assert r["ok"] is False and "isn't connected" in r["text"], r
        r = await device.ask(url, "peer-secret", "Pi Jarvis", {"type": "devices"})
        assert {"Phone", "Kitchen"} <= set(r["connected"]), r
        # an old-style result (no id): still a turn
        await pix.send(json.dumps({"type": "phone_result", "text": "no contact matches"}))
        await asyncio.sleep(0.2)
        assert turns == ["no contact matches"], turns
    # no token: not a peer, the device frame is ignored
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "hello", "device_id": "x"}))
        await ws.send(json.dumps({"type": "device", "device": "Phone", "frame": {"do": "ring"}}))
        try:
            await recv(ws, "device_result", 1)
            raise AssertionError("a non-peer ran a device action")
        except asyncio.TimeoutError:
            pass
    srv.cancel()

    # ---- timers
    p = os.path.join(D, "timers.json")
    T.run(p, ["add", "Kitchen", "600", "pasta"], now=1000)
    T.run(p, ["add", "Phone", "90", "lift", "--buzz", "Phone"], now=1000)
    out = T.run(p, [], now=1000)
    assert out == "1. pasta on Kitchen: 10m 0s left\n2. lift on Phone: 1m 30s left", out
    assert T.load(p)[1]["buzz"] == "Phone"
    assert T.due(p, now=1050) == []
    hit = T.due(p, now=1100)
    assert [t["label"] for t in hit] == ["lift"] and len(T.load(p)) == 1, hit
    T.run(p, ["cancel", "Pasta"])
    assert T.load(p) == []
    try:
        T.run(p, ["cancel", "nothing"])
        raise AssertionError("cancelled a timer that doesn't exist")
    except ValueError:
        pass
    print("OK")

asyncio.run(main())
