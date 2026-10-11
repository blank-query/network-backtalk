# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_timing_line.py
# Self-check: a reply's first terminal line carries its timing for the
# face (show.time: speech-to-text, then the ask to the first reply text);
# later lines and a typed ask's "heard" don't.
import asyncio, json, os, sys, tempfile, time
D = tempfile.mkdtemp()
with open(os.path.join(D, "cfg.json"), "w") as f:
    json.dump({"signals_dir": D}, f)
os.environ["BACKTALK_CONFIG"] = os.path.join(D, "cfg.json")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claude_agent_sdk import ResultMessage
from claude_agent_sdk.types import StreamEvent
from backtalk import brain as B, ears

class Sink:
    conn_id = "dev"
    def __init__(s): s.got = []
    def send(s, obj):
        if obj.get("type") == "line": s.got.append(obj)
    def is_live(s): return True
class Stub:
    def __getattr__(s, n): return lambda *a, **k: None
def ev(text): return StreamEvent(uuid="u", session_id="s", event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}})
def res(): return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s")
class Client:
    def __init__(s): s.q = asyncio.Queue()
    async def query(s, u): pass
    def receive_messages(s):
        async def gen():
            while True: yield await s.q.get()
        return gen()

async def main():
    b = B.WarmBrain(mouth=Stub(), bus=Stub())
    b._tally = lambda *a, **k: None; b._remember_session = lambda *a, **k: None
    async def nop(): pass
    b._pull_rate_limits = nop
    b._client = c = Client(); b._start_reader()
    sink = Sink()
    ears.HEARD[:] = [time.time(), 0.84]          # an utterance just transcribed
    b.ask("spoken", sink); await asyncio.sleep(0.3)
    for m in (ev("Good evening, sir. "), ev("All quiet. "), res()): c.q.put_nowait(m)
    await asyncio.sleep(1.2)
    first, *rest = sink.got
    t = first["show"]["time"]
    assert t.startswith("heard 0.8s · first word 0.") and t.endswith("s"), t
    assert all("show" not in l for l in rest), rest
    sink.got.clear()
    b.ask("typed", sink); await asyncio.sleep(0.05)   # HEARD already taken
    for m in (ev("Indeed. "), res()): c.q.put_nowait(m)
    await asyncio.sleep(1.2)
    t = sink.got[0]["show"]["time"]
    assert t.startswith("first word "), t
    print("timing line: ok")
asyncio.run(main())
