# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_ha_gate.py
# ${VAR} in mcp_servers is filled from the environment (a token stays out of
# backtalk.json), and the speaker tag says "voice: <name> <score>" only for a
# real voiceprint match, never for a device owner's name alone.
import json, os, sys, tempfile
import numpy as np
D = tempfile.mkdtemp()
with open(os.path.join(D, "cfg.json"), "w") as f:
    json.dump({"signals_dir": D, "agent_dir": D, "voiceprint_model": "fake",
               "mcp_servers": {"ha": {"type": "http", "url": "http://h/${BT_CHECK_UNSET}",
                                      "headers": {"Authorization": "Bearer ${BT_CHECK_TOK}"}},
                               "s": {"command": "x", "args": ["${BT_CHECK_TOK}", "$HOME"]}}}, f)
os.environ["BACKTALK_CONFIG"] = os.path.join(D, "cfg.json")
os.environ["BT_CHECK_TOK"] = "t0k"
os.environ.pop("BT_CHECK_UNSET", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk.config import CFG
from backtalk import voiceprint

m = CFG["mcp_servers"]
assert m["ha"]["headers"]["Authorization"] == "Bearer t0k"
assert m["ha"]["url"] == "http://h/${BT_CHECK_UNSET}"      # unset: left alone
assert m["s"]["args"] == ["t0k", "$HOME"]                   # only the ${} form

assert voiceprint.PATH.startswith(D)                        # never the live prints
rng = np.random.default_rng(1)
a, c = (v / np.linalg.norm(v) for v in rng.normal(size=(2, 192)))
for _ in range(3):
    voiceprint.add("sir", "phone", a)
assert voiceprint.speaker_tag(a, "kitchen") == ("voice: sir 1.00", "sir")
assert voiceprint.speaker_tag(a, "phone", "sir") == ("voice: sir 1.00", "sir")
assert voiceprint.speaker_tag(c, "phone", "sir") == ("sir, voice: unknown", None)
assert voiceprint.speaker_tag(None, "phone", "sir") == ("sir, voice: none", None)
print("OK")
