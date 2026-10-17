# Run: .venv/bin/python tests/check_controls.py (config, signals, and log in a temp dir)
# Self-check: the three controls (the bridge protocol). A press only
# queues (no interrupt reaches the brain or the bridge's control hook);
# "interrupt" and "abort" frames reach it; the talk key's pause holds local
# playback without dropping a sample and resumes it; the abort's answer
# parser; the brain's abort tools: stop_task per task, the SDK interrupt
# only for "everything"; Friday's brain maps stop_task to subagent.interrupt.
# The read-back ends in how to answer; a turn nobody asked for holds its
# speech while the abort menu is open or sir is talking into its device.
import asyncio, json, os, sys, tempfile, threading, time
tmp = tempfile.mkdtemp(prefix="bt-controls-")
with open(os.path.join(tmp, "backtalk.json"), "w") as f:
    json.dump({"agent_dir": tmp, "signals_dir": tmp}, f)
os.environ.update(BACKTALK_CONFIG=os.path.join(tmp, "backtalk.json"),
                  BACKTALK_LOG=os.path.join(tmp, "backtalk.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from claude_agent_sdk import ResultMessage
from claude_agent_sdk.types import StreamEvent
from backtalk import brain as B, mouth as M
from backtalk.brain_hermes import HermesClient
from backtalk.main import (abort_pick, abort_step, abort_readback, console_match, barges_in,
                           hold_reason, ABORT_WAIT_S, NAME)
from backtalk.web import BrowserBridge, Conn

# ---- the abort's answer
tasks = ["Research the bike pump prices", "Build the watch release", "a background task"]
for said, want in [("Everything.", "all"), (f"{NAME}, everything", "all"), ("stop all of them", "all"),
                   ("Never mind.", "none"), ("No.", "none"), ("Number two.", 1), ("the first one", 0),
                   ("3", 2), ("Stop the watch build", 1), ("bike pump one", 0),
                   ("banana", None), ("seven", None), ("", None)]:
    got = abort_pick(said, tasks)
    assert got == want, (said, got, want)
# a long remark naming a helper in passing is not an answer (2026-10-11: it stopped one)
helpers = ["Watch interrupt pill not firing", "App keeps keys unless truly revoked"]
said = "That was me holding the bill not firing Two app keeps Keys unless truly revoked"
assert abort_pick(said, helpers) is None and abort_step(said, helpers) == ("cancel", None)
for said, want in [("two", ("ask", 1)), ("app keeps keys", ("ask", 1)), ("everything", ("ask", "all")),
                   ("never mind", ("none", None)), ("what's the weather like", ("cancel", None))]:
    assert abort_step(said, helpers) == want, (said, abort_step(said, helpers), want)
# the confirmation: only a yes stops; no leaves it; anything else is a message
assert abort_step("Yes.", helpers, 1) == ("do", 1) and abort_step(f"{NAME}, yes", helpers, "all") == ("do", "all")
assert abort_step("No.", helpers, 1) == ("none", None)
assert abort_step("two app keeps keys", helpers, 1) == ("cancel", None)
# no background tasks: "Stop it?" was the question, so yes or everything stops the turn
assert abort_step("yes", []) == ("do", "all") and abort_step("everything", []) == ("do", "all")
assert abort_step("one", []) == ("cancel", None)
assert console_match(f"{NAME}, abort.") == "abort" and console_match("abort") is None
assert barges_in(f"{NAME}, abort", [])
# the read-back ends in how to answer (2026-10-11: a bare list left sir guessing)
assert abort_readback(helpers).endswith("Say a number, everything, or never mind.")
assert abort_readback(helpers[:1]).endswith("Stop it? Yes or no.")
assert abort_readback([]).endswith("Stop it? Yes or no.")
assert abort_step("yes", helpers[:1], 0) == ("do", 0), "one task: the read-back is the confirm"
# what holds a turn nobody asked for: the open menu (until it times out), sir talking
class C: recording = capturing = False
class S: conn = C()
idle = {"brain": None, "at": 0.0}
assert hold_reason(idle, S()) is None and hold_reason(idle, None) is None
assert hold_reason({"brain": 1, "at": time.monotonic()}, S()) == "the abort menu is open"
assert hold_reason({"brain": 1, "at": time.monotonic() - ABORT_WAIT_S - 1}, S()) is None, "no timeout"
S.conn.recording = True
assert hold_reason(idle, S()) == "sir is talking"
S.conn.recording, S.conn.capturing = False, True
assert hold_reason(idle, S()) == "sir is talking"
assert hold_reason(idle, None, mic_capturing=True) == "sir is talking"


class Bus:
    def __getattr__(s, n): return lambda *a, **k: None


class Client:
    def __init__(s): s.stopped, s.interrupts, s.q = [], 0, asyncio.Queue()
    async def query(s, u): pass
    async def interrupt(s): s.interrupts += 1
    async def stop_task(s, t):
        if t == "gone": raise RuntimeError("no such task")
        s.stopped.append(t)
    def receive_messages(s):
        async def gen():
            while True: yield await s.q.get()
        return gen()


class WS:
    def __init__(s, frames): s.frames, s.sent, s.remote_address = frames, [], ("127.0.0.1", 1)
    def __aiter__(s): return s._it()
    async def _it(s):
        for f in s.frames: yield f
    async def send(s, d): s.sent.append(d)
    async def close(s, *a): pass


async def main():
    # ---- the brain's abort tools
    b = B.WarmBrain(mouth=None, bus=Bus())
    b._client = c = Client()
    b._active_tasks, b._task_desc = {"t2", "t1"}, {"t1": "Research", "t2": None}
    assert b.running() == [("t1", "Research"), ("t2", "a background task")]
    assert await b.stop_task("t1") and not await b.stop_task("gone") and c.stopped == ["t1"]
    await b.interrupt()
    assert c.interrupts == 0, "a soft cut with no turn called the SDK interrupt"
    b._turn_active = True
    await b.interrupt()
    assert c.interrupts == 0 and b._discard_until_result, "the tap's cut must stay soft"
    await b.abort_turn()
    assert c.interrupts == 1, "everything must really stop the turn"

    # ---- Friday: stop_task is Hermes's subagent.interrupt
    h = object.__new__(HermesClient)
    h.sid, calls = "s1", []
    async def call(m, p, timeout=60):
        calls.append((m, p)); return {"found": p["subagent_id"] == "live"}
    h.call = call
    await h.stop_task("live")
    try:
        await h.stop_task("dead"); raise AssertionError("a missing subagent passed")
    except RuntimeError:
        pass
    assert calls[0] == ("subagent.interrupt", {"session_id": "s1", "subagent_id": "live"})

    # ---- the bridge: press queues, never a control; interrupt and abort are
    br = BrowserBridge({})
    got = []
    br.on_control = lambda conn, kind, *_: got.append(kind)
    conn = Conn(WS([json.dumps({"type": "hello", "device_id": "d"}), json.dumps({"type": "press"}),
                    json.dumps({"type": "interrupt"}), json.dumps({"type": "abort"})]), br)
    await conn.reader()
    assert got == ["interrupt", "abort"], got
    assert br._press_q.get_nowait()[1] is False, "a press must queue, not interrupt"
    ident = [json.loads(m) for m in conn.ws.sent if '"identity"' in m]
    assert ident and ident[0].get("controls") == 1, "the bridge must announce the controls"

    # ---- the talk key's pause: local playback holds, nothing is dropped
    chunks = [np.full(2205, i + 1, np.int16) for i in range(6)]
    M.synth_stream = lambda text, timeout=30.0: iter([(22050, ch) for ch in chunks])

    class Out:
        def __init__(s): s.got = []
        def write(s, pcm): s.got.append(int(pcm[0])); time.sleep(0.01)
    out = Out()
    states = []

    class StateBus(Bus):
        def set_state(s, name): states.append(name)
    m = M.Mouth(bus=StateBus())
    m._get_out = lambda rate: out
    m.pause()
    m.say("One sentence.")
    await asyncio.sleep(0.3)
    assert out.got == [], f"played while paused: {out.got}"
    assert "speaking" not in states, "speaking before any audio went out"
    m.resume()
    await asyncio.sleep(0.05)
    assert states[:1] == ["speaking"], f"speaking must mark the first audio: {states}"
    await asyncio.sleep(0.5)
    assert out.got == [1, 2, 3, 4, 5, 6], f"lost or reordered audio: {out.got}"
    out.got.clear()
    m.pause(); m.say("Again."); await asyncio.sleep(0.2)
    m.shut_up(); await asyncio.sleep(0.2)
    assert out.got == [], f"a stop while paused played audio: {out.got}"
    m.resume()

    # ---- a turn nobody asked for waits for the hold, then speaks; a dispatched one never waits
    said = []
    class Mouth:
        speaking = False
        def say_chunk(s, text, directions=None, sink=None):
            if text: said.append(text)
        def __getattr__(s, n): return lambda *a, **k: None
    b = B.WarmBrain(mouth=Mouth(), bus=Bus(), persist=False)
    b._tally = b._remember_session = lambda *a, **k: None
    async def nop(): pass
    b._pull_rate_limits = nop
    b._client = c = Client()
    why = ["the abort menu is open"]
    b.hold = lambda sink: why[0]
    b._start_reader()
    def ev(text): return StreamEvent(uuid="u", session_id="s", event={
        "type": "content_block_delta", "delta": {"type": "text_delta", "text": text}})
    res = ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                        is_error=False, num_turns=1, session_id="s")
    for m in (ev("The helper finished. "), ev("All done."), res):
        c.q.put_nowait(m)
    await asyncio.sleep(0.6)
    assert said == [], f"spoke over the abort menu: {said}"
    why[0] = "sir is talking"
    await asyncio.sleep(0.4)
    assert said == [], f"spoke over sir: {said}"
    why[0] = None
    await asyncio.sleep(1.2)
    assert said and said[0] == "The helper finished.", f"a released turn must speak: {said}"
    said.clear()
    why[0] = "the abort menu is open"
    b.ask("Answer me.", remote_sink=None)
    for m in (ev("Here you are. "), res):
        c.q.put_nowait(m)
    await asyncio.sleep(0.6)
    assert said == ["Here you are."], f"a dispatched turn was held: {said}"
    # an abort's "everything" while one is held drops it, never speaks it later
    said.clear()
    for m in (ev("Stale report. "), res):
        c.q.put_nowait(m)
    await asyncio.sleep(0.4)
    b._turn_active = True
    await b.abort_turn()
    why[0] = None
    await asyncio.sleep(1.2)
    assert said == [], f"a held turn spoke after everything stopped: {said}"
    print("controls self-check ok")

asyncio.run(main())
