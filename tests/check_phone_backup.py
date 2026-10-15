# Run: .venv/bin/python tests/check_phone_backup.py
# Self-check: with the phone's recognizer on, a hands-free utterance is
# captured but not transcribed (DEFERRED); the backup is transcribed only
# when asked (the phone heard nothing), and never when the phone won.
import json, os, sys, tempfile, wave
tmp = tempfile.mkdtemp(prefix="bt-backup-")
with open(os.path.join(tmp, "backtalk.json"), "w") as f:
    json.dump({"agent_dir": tmp, "signals_dir": tmp, "name": "Jarvis"}, f)
os.environ.update(BACKTALK_CONFIG=os.path.join(tmp, "backtalk.json"),
                  BACKTALK_LOG=os.path.join(tmp, "backtalk.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from backtalk import ears

with wave.open(os.path.join(os.path.dirname(__file__), "tap_clip.wav")) as w:
    speech = np.frombuffer(w.readframes(w.getnframes()), np.int16)
pcm = np.concatenate([np.zeros(16000, np.int16), speech, np.zeros(16000 * 3, np.int16)])


class Stream:
    def __init__(self): self.i = 0
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n):
        b = pcm[self.i:self.i + n]; self.i += n
        return b.reshape(-1, 1), False


calls = []
ears.transcribe = lambda p, vad=False: calls.append(len(p)) or "turn on the lights"
e = ears.Ears(aggressiveness=3, silence_ms=1200)

# the phone won: nothing transcribed at all
assert e.listen_once(stream=Stream(), defer=lambda: True) is ears.DEFERRED
assert e.last_pcm is not None and e.backup is not None and not calls
assert e.backup_text(False) == "" and e.backup is None and not calls

# the phone heard nothing: the backup is transcribed, whole
assert e.listen_once(stream=Stream(), defer=lambda: True) is ears.DEFERRED and not calls
assert e.backup_text(True) == "turn on the lights" and calls == [len(e.last_pcm)]

# phone recognizer off: transcribed as before
calls.clear()
assert e.listen_once(stream=Stream()) == "turn on the lights" and len(calls) == 1
print("phone backup ok")
