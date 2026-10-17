# Run: .venv/bin/python tests/check_interrupt_turn.py
# Self-check: Interrupt stops what sir is HEARING (sir, 2026-10-17). Every
# turn's audio and lines carry its turn id (the bridge protocol's TURNS);
# the live turn's answer is dropped only when its own audio is what plays
# (or it is asking permission, or nothing plays at all). Another turn's
# audio playing (an earlier reply still playing out on the phone) is
# dropped alone: the live turn carries on and its audio already queued on
# the phone stays. Exactly the failure: turn N playing on
# the phone after a press paused it, turn N+1's first sentence queued
# behind it, Interrupt tapped: N+1 was dropped, and the phone flushed its
# sentence too.
import asyncio, json, os, sys, tempfile, time, types
tmp = tempfile.mkdtemp(prefix="bt-intturn-")
with open(os.path.join(tmp, "backtalk.json"), "w") as f:
    json.dump({"agent_dir": tmp, "signals_dir": tmp}, f)
os.environ.update(BACKTALK_CONFIG=os.path.join(tmp, "backtalk.json"),
                  BACKTALK_LOG=os.path.join(tmp, "backtalk.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from claude_agent_sdk import ResultMessage
from claude_agent_sdk.types import StreamEvent
from backtalk import brain as B, mouth as M
from backtalk.main import cut_reply, stop_drops_turn
from backtalk.web import BrowserBridge, NO_REPORT

# (live turn, heard turn, asking)
assert not stop_drops_turn(8, 7, False)      # turn 7's audio plays, 8 in flight: 8 kept
assert stop_drops_turn(8, 8, False)          # the live turn's own audio: dropped
assert stop_drops_turn(8, None, False)       # nothing playing: the tap cancels the live turn
assert stop_drops_turn(8, 7, True)           # its permission ask: dropped
assert not stop_drops_turn(None, 7, False)   # nothing in flight: voice only
assert not stop_drops_turn(None, None, True)


class Ws:
    def __init__(s): s.sent = []
    async def send(s, x): s.sent.append(x if isinstance(x, bytes) else json.loads(x))


class Conn:
    def __init__(s, turns):
        s.id, s.turns, s.turn_sent, s.ws = "phone", turns, None, Ws()
    disconnected = recording = False; call = None; audio = True; face = peer = None


class Mouth:
    """The brain's mouth, minus the voice: each chunk goes to the device as
    real-time audio, 1 s a sentence, tagged with the turn the brain set."""
    speaking = False
    playing_turn = None
    def __init__(s): s.said, s.cut, s.turn = [], [], None
    def say_chunk(s, text, directions=None, sink=None):
        if text:
            s.said.append((text, s.turn))
            if sink is not None:
                sink.turn(s.turn)
                sink(24000, np.zeros(24000, dtype=np.int16))
    def shut_up(s, turn=None): s.cut.append(turn)
    def __getattr__(s, n): return lambda *a, **k: None


class Client:
    def __init__(s): s.q = asyncio.Queue()
    async def query(s, u): pass
    def receive_messages(s):
        async def gen():
            while True: yield await s.q.get()
        return gen()


def ev(text): return StreamEvent(uuid="u", session_id="s", event={
    "type": "content_block_delta", "delta": {"type": "text_delta", "text": text}})
def res(): return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                                is_error=False, num_turns=1, session_id="s")


async def failing_sequence(turns: bool):
    """That sequence on a phone; `turns`: the app reports the turn it
    plays (app 108 on), else the bridge estimates."""
    br = BrowserBridge({"host": "127.0.0.1", "port": 1})
    br._loop = asyncio.get_running_loop()
    c = Conn(turns)
    br._conns.add(c)
    sink = br.make_sink(c)
    m = Mouth()
    b = B.WarmBrain(mouth=m)
    b._tally = lambda *a, **k: None
    b._remember_session = lambda *a, **k: None
    async def nop(): pass
    b._pull_rate_limits = nop
    b._client = Client()
    b.remote_sink = br.make_recent_sink()
    br.used(sink)
    b._start_reader()
    q = b._client.q
    async def settle(): await asyncio.sleep(0.05)

    # turn N: a long answer, sent to the phone (3 s of it)
    b.ask("first", remote_sink=sink)
    n = b.live_turn
    for s in ("One. ", "Two. ", "Three. "):
        await q.put(ev(s)); await settle()
    await q.put(res()); await settle()
    assert b.live_turn is None and {t for _, t in m.said} == {n}, m.said
    # sir presses to ask N+1: the phone holds N's audio for the 4 s press
    br.held(c.id, time.monotonic() - 4)
    b.ask("second", remote_sink=sink)
    n1 = b.live_turn
    assert n1 is not None and n1 > n
    await q.put(ev("Here's your second answer, sir. ")); await settle()
    assert m.said[-1] == ("Here's your second answer, sir.", n1)
    # the phone is still playing N, N+1's sentence queued behind it
    assert br.heard(c.id) == n
    frames = c.ws.sent
    marks = [f["id"] for f in frames if isinstance(f, dict) and f.get("type") == "turn"]
    assert marks == [n, n1], marks
    assert isinstance(frames[frames.index({"type": "turn", "id": n1}) + 1], bytes)   # the mark leads its audio
    lines = [f for f in frames if isinstance(f, dict) and f.get("type") == "line"]
    assert {l["turn"] for l in lines} == {n, n1}

    # Interrupt: the app reports N (or the bridge estimates N)
    await settle()
    c.ws.sent = []
    await cut_reply(b, br, "the interrupt button", False, c, n if turns else NO_REPORT)
    await settle()
    assert not b._discard_until_result, "N+1 must not be dropped"
    assert m.cut == [n], m.cut                               # only N's audio, here
    assert {"type": "stop", "turn": n} in c.ws.sent, c.ws.sent   # and on the phone
    if turns:
        # the phone keeps N+1's sentence: the estimate follows it
        assert [t for t, _ in br.played[c.id]] == [n1], br.played
        assert br.heard(c.id) == n1
    else:
        assert c.id not in br.played      # an older app drops everything it had
    # N+1 carries on and its answer is spoken
    await q.put(ev("And the rest of it. ")); await settle()
    await q.put(res()); await settle()
    assert m.said[-1] == ("And the rest of it.", n1), m.said

    # the live turn's own audio playing: that turn is dropped, all audio goes
    br.played.clear()       # N+1's audio has played out
    b.ask("third", remote_sink=sink)
    n2 = b.live_turn
    await q.put(ev("Turn three starts. ")); await settle()
    c.ws.sent = []
    await cut_reply(b, br, "the interrupt button", False, c, n2 if turns else NO_REPORT)
    await settle()
    assert b._discard_until_result and m.cut[-1] is None
    assert {"type": "stop"} in c.ws.sent, c.ws.sent
    await q.put(ev("Turn three rest. ")); await settle()
    await q.put(res()); await settle()
    assert m.said[-1] == ("Turn three starts.", n2), m.said

    # nothing playing while a turn thinks: the tap cancels it
    br.played.clear()
    b.ask("fourth", remote_sink=sink)
    await cut_reply(b, br, "the interrupt button", False, c, None if turns else NO_REPORT)
    assert b._discard_until_result
    await q.put(res()); await settle()
    b._reader_task.cancel()


async def bridge_estimate():
    """heard(): what the phone plays now, press pauses included."""
    br = BrowserBridge({"host": "127.0.0.1", "port": 1})
    br._loop = asyncio.get_running_loop()
    c = Conn(False)
    sink = br.make_sink(c)
    assert br.heard() is None
    sink.turn(1); sink(24000, np.zeros(24000 * 3, dtype=np.int16))    # 3 s of turn 1
    sink.turn(2); sink(24000, np.zeros(24000, dtype=np.int16))        # then 1 s of turn 2
    assert br.heard(c.id) == 1 and br.heard() == 1
    # 3.5 s on: turn 2 is playing
    for seg in br.played[c.id]:
        seg[1] -= 3.5
    assert br.heard(c.id) == 2
    # a 4 s press paused it: what was left now ends 4 s later
    br.held(c.id, time.monotonic() - 4)
    assert br.played[c.id][-1][1] > time.monotonic() + 4
    # all played out a while ago: nothing
    for seg in br.played[c.id]:
        seg[1] -= 10
    assert br.heard(c.id) is None
    # a stop to an older app empties it
    sink(24000, np.zeros(24000, dtype=np.int16))
    sink.stop(2)
    assert br.heard() is None


def mouth_cut():
    """The real Mouth: shut_up(turn) stops that turn and skips its queued
    sentences; a later turn's play on."""
    played = []
    def fake_synth(text, timeout=30.0):
        for _ in range(6):
            yield 24000, np.zeros(2400, dtype=np.int16)
    M.synth_stream = fake_synth
    class Out:
        active = True
        def start(self): pass
        def write(self, pcm): time.sleep(len(pcm) / 24000)
        def close(self, **_): pass
    M.sd.OutputStream = lambda **_: Out()
    class Sink:
        conn = None; conn_id = None
        def __init__(s): s.marks = []
        def __call__(s, rate, pcm): played.append(s.marks[-1])
        def turn(s, t): s.marks.append(t)
        def reply_done(s): pass
    sk = Sink()
    m = M.Mouth()
    m.ducker = types.SimpleNamespace(speech_start=lambda: None, speech_end=lambda: None)
    m.turn = 101
    m.say_chunk("Turn one first.", remote_sink=sk)
    m.say_chunk("Turn one second.", remote_sink=sk)
    m.turn = 102
    m.say_chunk("Turn two.", remote_sink=sk)
    time.sleep(0.3)
    assert m.speaking and m.playing_turn == 101
    m.shut_up(102 - 1)
    m.wait_done(5)
    # 12 blocks a sentence: 101 cut inside its first, its second skipped, 102 whole
    assert played[-12:] == [102] * 12 and set(played[:-12]) == {101}, played
    assert played.count(101) < 12, played
    # a whole stop still stops everything
    played.clear()
    m.say_chunk("Again.", remote_sink=sk)
    time.sleep(0.2)
    m.shut_up()
    m.wait_done(5)
    assert len(played) < 12, played


asyncio.run(failing_sequence(turns=True))
asyncio.run(failing_sequence(turns=False))
asyncio.run(bridge_estimate())
mouth_cut()
print("interrupt-turn self-check ok")
