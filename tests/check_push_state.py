# Run: .venv/bin/python tests/check_push_state.py
# Self-check: pushed state (?push=1, a wall display's native face) follows
# a device's own entry while a dedicated session owns it, as the face
# server's /state?device= does; other devices see the shared bus.
import json, os, sys, tempfile, time, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk.web import BrowserBridge

d = tempfile.mkdtemp()
def put(n, v): open(os.path.join(d, n), "w").write(v)
put(".voice_state", "thinking"); put(".voice_tasks", "2"); put(".voice_active_conn", "phone")
put(".voice_devices", json.dumps({
    "echo": {"owned": True, "state": "idle", "samples": [3000] * 64, "wave_ts": time.time(), "tasks": 1,
             "timers": [{"label": "pasta", "at": 1}]},
    "fold": {"timers": [{"label": "tea", "at": 2}]}}))
me = types.SimpleNamespace(signals_dir=d)
e = BrowserBridge.bus_state(me, "echo")
assert (e["state"], e["level"], e["tasks"], e["active_conn"]) == ("speaking", 1.0, 1, "echo"), e
assert e["timers"][0]["label"] == "pasta" and not e["loading"]
f = BrowserBridge.bus_state(me, "fold")
assert (f["state"], f["tasks"], f["active_conn"]) == ("thinking", 2, "phone"), f
assert f["timers"][0]["label"] == "tea"
n = BrowserBridge.bus_state(me, "nobody")
assert n["state"] == "thinking" and n["timers"] == []
print("ok")
