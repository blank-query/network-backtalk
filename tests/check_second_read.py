# Run: .venv/bin/python tests/check_second_read.py
# Self-check: talk-over with no name in its transcript gets a second,
# whole-clip read, and is cut only if that read has the name; the open
# mic keeps ~600 ms of audio from before an utterance opens (PRE_ROLL),
# once, with nothing doubled.
import json, os, sys, tempfile, wave
tmp = tempfile.mkdtemp(prefix="bt-reread-")
with open(os.path.join(tmp, "backtalk.json"), "w") as f:
    json.dump({"agent_dir": tmp, "signals_dir": tmp, "name": "Jarvis"}, f)
os.environ.update(BACKTALK_CONFIG=os.path.join(tmp, "backtalk.json"),
                  BACKTALK_LOG=os.path.join(tmp, "backtalk.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from backtalk import ears, main
from backtalk.main import barges_in, second_read

clip = np.ones(16000, np.int16)
calls = []


def fake(answer):
    def reread(pcm, name):
        calls.append(name)
        if isinstance(answer, Exception):
            raise answer
        return answer
    return reread


main.reread = fake("Jarvis stop")
assert second_read("Jarvis, stop.", clip) == "Jarvis, stop." and not calls   # named: no second read
main.reread = fake("stop")
out = second_read("I'm sorry, stop", clip)                     # neither read has the name
assert out == "I'm sorry, stop" and not barges_in(out, []) and calls == ["Jarvis"]
main.reread = fake("Jarvis is out")
out = second_read("", clip)                                    # first read empty, second names it
assert out == "Jarvis is out" and barges_in(out, [])
out = second_read("I'm going to show you how to do it", clip)
assert barges_in(out, [])
main.reread = fake("Javi, enough")                             # a close mishearing counts
assert barges_in(second_read("enough", clip), [])
main.reread = fake(RuntimeError("no model"))
assert second_read("hello", clip) == "hello"                   # a failed read keeps the first
main.reread = fake(None)
assert second_read("hello", clip) == "hello"                   # whisper setup: nothing to add
assert second_read("hello", None) == "hello"
# with whisper as the engine the second read stands down
assert ears.reread(clip, "Jarvis") is None

# pre-roll: the utterance starts well ahead of its trigger, and is one
# contiguous slice of what came in (no frame doubled or dropped)
with wave.open(os.path.join(os.path.dirname(__file__), "tap_clip.wav")) as w:
    speech = np.frombuffer(w.readframes(w.getnframes()), np.int16)
rng = np.random.default_rng(1)
lead = (rng.standard_normal(16000) * 3).astype(np.int16)        # 1 s of faint hiss
pcm = np.concatenate([lead, speech, np.zeros(16000 * 3, np.int16)])


class Stream:
    i = 0
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n):
        b = pcm[self.i:self.i + n]; self.i += n
        return b.reshape(-1, 1), False


ears.transcribe = lambda pcm, vad=False: "ok"
e = ears.Ears(aggressiveness=3, silence_ms=1200)
assert e.listen_once(stream=Stream()) == "ok"
got = e.last_pcm
start = next(i for i in range(0, len(pcm) - len(got) + 1, ears.FRAME_LEN)
             if np.array_equal(pcm[i:i + len(got)], got))
onset = len(lead) + int(np.argmax(np.abs(speech) > 300))
ahead = (onset - start) / 16000
assert ahead >= 0.3, f"only {ahead:.2f} s kept ahead of the speech"
print(f"second read ok; pre-roll keeps {ahead:.2f} s ahead of the speech, nothing doubled")
