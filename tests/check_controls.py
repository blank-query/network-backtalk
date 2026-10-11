# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_controls.py
# Self-check: the three controls (the Bridge Protocol note). A press only
# queues (no interrupt reaches the brain or the bridge's control hook);
# "interrupt" and "abort" frames reach it; the talk key's pause holds local
# playback without dropping a sample and resumes it; the abort's answer
# parser; the brain's abort tools: stop_task per task, the SDK interrupt
# only for "everything"; Friday's brain maps stop_task to subagent.interrupt.
import asyncio, json, os, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from backtalk import brain as B, mouth as M
from backtalk.brain_hermes import HermesClient
from backtalk.main import abort_pick, console_match, barges_in
from backtalk.web import BrowserBridge, Conn

# ---- the abort's answer
tasks = ["Research the oil filter prices", "Build the watch release", "a background task"]
for said, want in [("Everything.", "all"), ("Jarvis, everything", "all"), ("stop all of them", "all"),
                   ("Never mind.", "none"), ("No.", "none"), ("Number two.", 1), ("the first one", 0),
                   ("3", 2), ("Stop the watch build", 1), ("oil filter one", 0),
                   ("banana", None), ("seven", None), ("", None)]:
    got = abort_pick(said, tasks)
    assert got == want, (said, got, want)
assert console_match("Jarvis, abort.") == "abort" and console_match("abort") is None
assert barges_in("Jarvis, abort", [])


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
    br.on_control = lambda conn, kind: got.append(kind)
    conn = Conn(WS([json.dumps({"type": "hello", "device_id": "d"}), json.dumps({"type": "press"}),
                    json.dumps({"type": "interrupt"}), json.dumps({"type": "abort"})]), br)
    await conn.reader()
    assert got == ["interrupt", "abort"], got
    assert br._press_q.get_nowait()[1] is False, "a press must queue, not interrupt"

    # ---- the talk key's pause: local playback holds, nothing is dropped
    chunks = [np.full(2205, i + 1, np.int16) for i in range(6)]
    M.synth_stream = lambda text, timeout=30.0: iter([(22050, ch) for ch in chunks])

    class Out:
        def __init__(s): s.got = []
        def write(s, pcm): s.got.append(int(pcm[0])); time.sleep(0.01)
    out = Out()
    m = M.Mouth(bus=Bus())
    m._get_out = lambda rate: out
    m.pause()
    m.say("One sentence.")
    await asyncio.sleep(0.3)
    assert out.got == [], f"played while paused: {out.got}"
    m.resume()
    await asyncio.sleep(0.5)
    assert out.got == [1, 2, 3, 4, 5, 6], f"lost or reordered audio: {out.got}"
    out.got.clear()
    m.pause(); m.say("Again."); await asyncio.sleep(0.2)
    m.shut_up(); await asyncio.sleep(0.2)
    assert out.got == [], f"a stop while paused played audio: {out.got}"
    m.resume()
    print("controls self-check ok")

asyncio.run(main())
