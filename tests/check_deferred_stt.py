# Run: .venv/bin/python tests/check_deferred_stt.py
# Self-check: a deferred ears.Session streams nothing into Moonshine while
# the press runs, and still transcribes the whole press at finish(); a
# cancelled deferred session never touches the model.
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from backtalk import ears

streams = []


class Stream:
    def __init__(self): self.samples = 0; streams.append(self)
    def start(self): pass
    def add_audio(self, a, rate): self.samples += len(a)
    def stop(self):
        line = type("L", (), {"text": f"{self.samples} samples"})
        return type("T", (), {"lines": [line]})
    def close(self): pass


class Moon:
    def create_stream(self, update_interval): return Stream()


ears.CFG["stt_engine"] = "moonshine"   # whatever backtalk.json says
ears._moon = Moon()
chunk = np.ones(1600, np.int16)

s = ears.Session(defer=True)
for _ in range(5):
    s.add(chunk)
assert not streams, "deferred session streamed during the press"
assert s.finish() == "8000 samples", streams

streams.clear()
s = ears.Session(defer=True)
s.add(chunk); s.cancel()
assert not streams

s = ears.Session()
assert len(streams) == 1        # the default still streams from the start
s.add(chunk)
assert s.finish() == "1600 samples"
print("deferred stt ok")
