# Run: .venv/bin/python tests/check_text_only.py
# Self-check: a device whose hello said "audio": false (the terminal chat)
# gets no speech synthesized for its turns unless this machine's speakers
# play them (web.local_playback_on_remote_turn, desktop unmuted); a device
# that plays audio still gets it. The bridge's sink sends it no audio frames.
import json, os, sys, tempfile, time, types
import numpy as np
tmp = tempfile.mkdtemp()
with open(os.path.join(tmp, "backtalk.json"), "w") as f:
    json.dump({"agent_dir": tmp, "signals_dir": tmp,
               "web": {"local_playback_on_remote_turn": False}}, f)
os.environ.update(BACKTALK_CONFIG=os.path.join(tmp, "backtalk.json"),
                  BACKTALK_LOG=os.path.join(tmp, "backtalk.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk import mouth as M, signals, web
from backtalk.config import CFG

synths, written = [], []
def fake_synth(text, timeout=30.0):
    synths.append(text)
    yield 24000, np.zeros(240, dtype=np.int16)
M.synth_stream = fake_synth

class Out:
    active = True
    def start(self): pass
    def write(self, pcm): written.append(len(pcm))
    def close(self, **_): pass
M.sd.OutputStream = lambda **_: Out()

class Sink:
    def __init__(self, audio):
        self.conn = types.SimpleNamespace(loopback=True, audio=audio)
        self.conn_id, self.pcm, self.done, self.sent = "dev", 0, 0, []
    def __call__(self, rate, pcm): self.pcm += len(pcm)
    def reply_done(self): self.done += 1
    def send(self, obj): self.sent.append(obj)

m = M.Mouth()
m.ducker = types.SimpleNamespace(speech_start=lambda: None, speech_end=lambda: None)   # never touch Spotify

def run(sink):
    synths.clear(); written.clear()
    m.say_chunk("Hello there.", remote_sink=sink)
    time.sleep(0.3)
    m.wait_done(5)

assert not signals.muted()
s = Sink(audio=False); run(s)
assert not synths and s.pcm == 0 and s.done == 1, (synths, s.pcm, s.done)   # terminal chat: no synthesis, turn still ends
assert open(os.path.join(tmp, ".voice_state")).read() == "idle"
s = Sink(audio=True); run(s)
assert synths and s.pcm > 0 and not written, (synths, s.pcm, written)       # a device with audio: hears it
CFG["web"]["local_playback_on_remote_turn"] = True
s = Sink(audio=False); run(s)
assert synths and written, (synths, written)                                # the desk plays it: synthesized
open(os.path.join(tmp, ".voice_muted"), "w").close()
s = Sink(audio=False); run(s)
assert not synths and not written and s.done == 1, (synths, written)        # ...unless the desk is muted
os.remove(os.path.join(tmp, ".voice_muted"))

# the bridge: a hello's "audio": false sticks to the connection, and its
# sink sends it text but no audio frames (a scratch bridge on a spare port)
import asyncio, websockets
PORT = 18798

async def bridge():
    br = web.BrowserBridge({"host": "127.0.0.1", "port": PORT})
    asyncio.ensure_future(br.serve())
    await asyncio.sleep(0.3)
    for extra, want in (({"audio": False}, False), ({}, True)):
        async with websockets.connect(f"ws://127.0.0.1:{PORT}", max_size=None) as ws:
            await ws.send(json.dumps({"type": "hello", "device_id": f"terminal-{want}",
                                      "model": "Desktop terminal", **extra}))
            await asyncio.sleep(0.3)
            c = next(c for c in br._conns if c.id == f"terminal-{want}")
            assert c.audio is want, (extra, c.audio)
            sink = br.make_sink(c)
            sink(24000, np.ones(240, dtype=np.int16))
            sink.send({"type": "line", "text": "Hello there."})
            got = []
            try:
                while True:
                    got.append(await asyncio.wait_for(ws.recv(), 0.5))
            except asyncio.TimeoutError:
                pass
            assert any(isinstance(g, str) and "Hello there." in g for g in got), got
            assert any(isinstance(g, bytes) for g in got) is want, (extra, got)

asyncio.run(bridge())
print("ok")
