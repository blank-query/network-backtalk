# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_speed.py
# Self-check: the face's tok/s readout. The brain turns a model call's
# streamed output tokens into a generation speed; a local server's log
# (a local server's timing line) gives generation and read speeds; both land in
# .voice_speed and ride the pushed state frame.
import asyncio, json, os, sys, tempfile, threading, time
D = tempfile.mkdtemp()
with open(os.path.join(D, "cfg.json"), "w") as f:
    json.dump({"signals_dir": D}, f)
os.environ["BACKTALK_CONFIG"] = os.path.join(D, "cfg.json")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claude_agent_sdk import ResultMessage
from claude_agent_sdk.types import StreamEvent
from backtalk import brain as B, signals
from backtalk.web import BrowserBridge

SPEED = os.path.join(D, ".voice_speed")
speed = lambda: json.load(open(SPEED))

# ---- from the SDK stream: 100 output tokens over ~0.5 s of streaming
class Bus:
    def __getattr__(s, n): return getattr(signals, n) if n == "set_speed" else (lambda *a, **k: None)
def ev(e): return StreamEvent(uuid="u", session_id="s", event=e)
def res(): return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s")
class Client:
    async def receive_messages(self):
        yield ev({"type": "message_start"})
        yield ev({"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hm"}})
        await asyncio.sleep(0.5)
        yield ev({"type": "message_delta", "usage": {"output_tokens": 100}})
        yield res()
b = B.WarmBrain(bus=Bus())
b._client = Client()
asyncio.run(b._read_forever())
g = speed()["gen"]
assert 150 < g < 210, g

# ---- from a server log: only lines written after the tail starts count
LOG = os.path.join(D, "server.log")
line = ("llm serve: prompt 47215 tokens = 46724 reused + 491 read in 1727 ms (284.4 tok/s), "
        "98 generated in 3086 ms ({} tok/s), drafts accepted 59 of 70, 6 checkpoints\n")
open(LOG, "w").write(line.format("99.9"))
threading.Thread(target=signals.tail_speed_log, args=(LOG,), daemon=True).start()
time.sleep(0.8)
assert speed()["gen"] == g, "an old log line was read"
open(LOG, "a").write(line.format("31.8"))
time.sleep(1.2)
s = speed()
assert s["gen"] == 31.8 and s["read"] == 284.4, s

# ---- in the state frame a device without a face server gets
st = BrowserBridge.bus_state(type("X", (), {"signals_dir": D})(), "dev")
assert st["speed"]["gen"] == 31.8, st
print("speed: ok")
