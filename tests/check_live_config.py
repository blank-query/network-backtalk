# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_live_config.py
# Self-check: backtalk.json is live. A change is re-read (config.reload),
# CFG is updated in place, an open mic's silence_frames follow it, the log
# names what changed, a file that won't parse keeps the old values, and
# connected devices get {"type": "settings", "open_mic_silence_ms": N} on
# hello and again on the change.
import asyncio, json, os, sys, tempfile
D = tempfile.mkdtemp()
P = os.path.join(D, "backtalk.json")
with open(P, "w") as f:
    json.dump({"open_mic_silence_ms": 2200, "speed": 1.0}, f)
os.environ["BACKTALK_CONFIG"] = P
os.environ.setdefault("BACKTALK_LOG", os.path.join(D, "bt.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import websockets
from backtalk import config, ears
from backtalk.config import CFG
from backtalk.web import BrowserBridge

LOG = os.environ["BACKTALK_LOG"]
cfg_id = id(CFG)
e = ears.Ears(aggressiveness=2)
assert e.silence_frames == 2200 // ears.FRAME_MS
assert ears.Ears(silence_ms=1200).silence_frames == 1200 // ears.FRAME_MS   # an explicit pause stays
assert config.reload() == {}                                            # unchanged: nothing


def write(obj):
    st = os.stat(P)
    with open(P, "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))
    os.utime(P, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))   # a new mtime even on a coarse clock


def logged():
    with open(LOG) as f:
        return f.read()


CFG["mic_mode"] = "open"          # a session-only flip of a key the file didn't change...
write({"open_mic_silence_ms": 1800, "speed": 1.0, "model": "x"})
ch = config.reload()
assert set(ch) == {"open_mic_silence_ms", "model"}, ch
assert id(CFG) == cfg_id and CFG["open_mic_silence_ms"] == 1800
assert CFG["mic_mode"] == "open"  # ...stands
assert e.silence_frames == 1800 // ears.FRAME_MS
out = logged()
assert "[config] reloaded: model" in out and "open_mic_silence_ms 2200 -> 1800" in out, out
assert '"x" (at the next restart)' in out and "1800 (at the next" not in out

write("{ not json")
assert config.reload() == {} and CFG["open_mic_silence_ms"] == 1800
assert "didn't parse, keeping the old values" in logged()


async def recv(ws, kind, t=3):
    while True:
        m = await asyncio.wait_for(ws.recv(), t)
        if isinstance(m, str) and json.loads(m).get("type") == kind:
            return json.loads(m)


async def main():
    br = BrowserBridge({"host": "127.0.0.1", "port": 18797})
    br._token = "peer-secret"
    br.devices_file = os.path.join(D, "devices.json")
    srv = asyncio.ensure_future(br.serve())
    await asyncio.sleep(0.3)
    url = "ws://127.0.0.1:18797"
    async with websockets.connect(url) as p, websockets.connect(url) as peer:
        await p.send(json.dumps({"type": "hello", "device_id": "p", "model": "Pixel 8 Pro"}))
        assert await recv(p, "settings") == {"type": "settings", "open_mic_silence_ms": 1800}
        await peer.send(json.dumps({"type": "hello", "device_id": "q", "token": "peer-secret", "peer": "Pi"}))
        await recv(peer, "peer_ok")
        write({"open_mic_silence_ms": 1500})
        if "open_mic_silence_ms" in config.reload():     # what main.py's _config_watch does
            br.push_settings()
        assert (await recv(p, "settings"))["open_mic_silence_ms"] == 1500
        try:
            await recv(peer, "settings", 0.5)
            raise AssertionError("a peer got a settings frame")
        except asyncio.TimeoutError:
            pass
    await br.stop()
    srv.cancel()

asyncio.run(main())
assert e.silence_frames == 1500 // ears.FRAME_MS
print("check_live_config: ok")
