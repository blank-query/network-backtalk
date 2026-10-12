# Run: .venv/bin/python tests/check_mute.py
# Self-check: a muted desktop (signals_dir/.voice_muted) synthesizes nothing
# for this machine's speakers or its own windows (a loopback device), while
# a device elsewhere that asked still gets its audio, never the local speaker.
import json, os, sys, tempfile, time, types
import numpy as np
tmp = tempfile.mkdtemp()
with open(os.path.join(tmp, "backtalk.json"), "w") as f:
    json.dump({"agent_dir": tmp, "signals_dir": tmp}, f)
os.environ.update(BACKTALK_CONFIG=os.path.join(tmp, "backtalk.json"),
                  BACKTALK_LOG=os.path.join(tmp, "backtalk.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk import mouth as M, signals

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
    def __init__(self, loopback):
        self.conn = types.SimpleNamespace(loopback=loopback)
        self.conn_id, self.audio, self.done = "dev", 0, 0
    def __call__(self, rate, pcm): self.audio += len(pcm)
    def reply_done(self): self.done += 1
    def send(self, obj): pass

m = M.Mouth()
m.ducker = types.SimpleNamespace(speech_start=lambda: None, speech_end=lambda: None)   # never touch Spotify

def run(sink):
    synths.clear(); written.clear()
    m.say_chunk("Hello there.", remote_sink=sink)
    time.sleep(0.3)
    m.wait_done(5)

mute = os.path.join(tmp, ".voice_muted")
open(mute, "w").close()
assert signals.muted()
run(None)
assert not synths and not written, (synths, written)          # this machine's own turn: silent
s = Sink(loopback=True); run(s)
assert not synths and s.audio == 0 and s.done == 1, (synths, s.audio, s.done)   # the face window: silent, turn still ends
s = Sink(loopback=False); run(s)
assert synths and s.audio > 0 and not written, (synths, s.audio, written)       # a phone that asked: hears it, desk stays quiet
assert open(os.path.join(tmp, ".voice_state")).read() == "idle"

os.remove(mute)
assert not signals.muted()
run(None)
assert synths and written, (synths, written)                   # unmuted: back to normal
print("ok")
