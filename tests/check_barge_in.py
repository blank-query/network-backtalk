# Run: .venv/bin/python tests/check_barge_in.py
# Self-check: hands-free speech over a reply stops it only when it says the
# name (a stop command included); anything else, a known voice or not, queues
# and the reply plays on (sir, 2026-10-11, the first real cook).
import json, os, sys, tempfile
tmp = tempfile.mkdtemp(prefix="bt-barge-")    # its own config: the phrases below say "Jarvis"
with open(os.path.join(tmp, "backtalk.json"), "w") as f:
    json.dump({"agent_dir": tmp, "signals_dir": tmp, "name": "Jarvis"}, f)
os.environ.update(BACKTALK_CONFIG=os.path.join(tmp, "backtalk.json"),
                  BACKTALK_LOG=os.path.join(tmp, "backtalk.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk.main import barges_in

assert barges_in("Jarvis, what about the bike pump?", ["sir"])        # the name
assert barges_in("Jarvis, what about the bike pump?", ["sir", "maam"])
assert barges_in("Javi, what's next?", [])                              # a close mishearing
assert not barges_in("About three quarters of an inch", ["maam"])       # an answer: queued
assert not barges_in("Thank you. Thank you.", ["maam"])                     # room noise, the other print
assert not barges_in("", ["maam"])
assert not barges_in("what time is it", [])
for s_ in ("Jarvis, stop.", "Jarvis stop talking", "Javi, enough!",
           "Jarvis, shut up", "Jarvis, hold on"):
    assert barges_in(s_, []) and barges_in(s_, ["sir", "maam"]), s_    # stop command, anyone
assert not barges_in("stop", [])                                        # needs the name
print("barge-in self-check ok")
