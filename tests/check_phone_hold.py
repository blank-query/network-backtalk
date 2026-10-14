"""The phone's hands-free segments are held until the utterance ends
(main.phone_done), not sent one by one. Timeline from the Pi log of
2026-10-13: segments at 36, 37, and 43 s; the Pi's ear ended the
one 20 s utterance at 49 s. Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_phone_hold.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk.main import phone_done  # noqa: E402

Q = 2.0   # open_mic_silence_ms 2000
# mid-utterance: the Pi is capturing and hasn't ended anything since
for now in (37.0, 43.5, 48.9):
    assert not phone_done(43.0, 15.0, True, now, Q), now
# the Pi's ear ends the utterance after the last words: send
assert phone_done(43.0, 49.0, False, 49.1, Q)
assert phone_done(43.0, 49.0, True, 49.1, Q)     # even if a new one already began
# the Pi never caught it: the phone's own quiet ends it, once nothing captures
assert not phone_done(43.0, 15.0, False, 44.0, Q)
assert phone_done(43.0, 15.0, False, 45.0, Q)
assert not phone_done(43.0, 15.0, True, 60.0, Q)  # a capture still running: wait for its end
print("ok")
