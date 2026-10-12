# Run: .venv/bin/python tests/check_reply_routing.py
# Self-check, the one routing rule (Bridge Protocol, "Where a reply goes"):
# a reply goes ONLY to the device whose message started the turn; a turn
# nobody asked for (a helper finishing) goes to the device sir last used
# for a real message (never an agent channel: a peer, claude-*, terminal-*),
# falling back to the next most recent still connected; no other device gets
# its audio. A scratch bridge (temp config, signals and log in /tmp, a spare
# port) with real socket clients: phone, watch (its own socket, as the
# phone's WatchRelay opens it), desk unit, this machine's face, the laptop
# Claude, the terminal chat, and a peer; the real brain reader, fed by a
# fake SDK stream.
import asyncio, inspect, json, os, sys, tempfile
tmp = tempfile.mkdtemp(prefix="bt-routing-")
PORT = 18797
with open(os.path.join(tmp, "backtalk.json"), "w") as f:
    json.dump({"agent_dir": tmp, "signals_dir": tmp,
               "web": {"enabled": True, "host": "127.0.0.1", "port": PORT}}, f)
os.environ.update(BACKTALK_CONFIG=os.path.join(tmp, "backtalk.json"),
                  BACKTALK_LOG=os.path.join(tmp, "backtalk.log"), JARVIS_PEER_TOKEN="scratch")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import websockets
from claude_agent_sdk import ResultMessage
from claude_agent_sdk.types import StreamEvent
from backtalk import brain as B
from backtalk.web import BrowserBridge


class Mouth:
    """mouth.py's routing, minus the voice: each sentence's audio and its
    reply_done go to the sink it was queued with (local playback off)."""
    speaking = False
    def say_chunk(self, text, directions=None, sink=None):
        if text and sink is not None:
            sink(24000, np.ones(240, dtype=np.int16))
            sink.reply_done()
    def __getattr__(self, n): return lambda *a, **k: None


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


def new_brain():
    b = B.WarmBrain(mouth=Mouth())
    b._tally = lambda *a, **k: None
    b._remember_session = lambda *a, **k: None
    async def nop(): pass
    b._pull_rate_limits = nop
    b._client = Client()
    b._start_reader()
    return b


async def main():
    br = BrowserBridge({"host": "127.0.0.1", "port": PORT})
    asyncio.ensure_future(br.serve())
    await asyncio.sleep(0.3)
    brain = new_brain()
    brain.remote_sink = br.make_recent_sink()
    peers = {}

    def on_text(conn, text, spoken=False):
        # main.py: a peer gets its own session; anyone else is handle()
        if conn.peer:
            if conn.id not in peers:
                peers[conn.id] = new_brain()
                peers[conn.id].remote_sink = br.make_sink(conn)
            peers[conn.id].ask(text, br.make_sink(conn))
            return
        sink = br.make_sink(conn)
        br.used(sink)
        brain.ask(text, sink)
    br.on_text = on_text

    url = f"ws://127.0.0.1:{PORT}"
    hellos = {"phone": {"device_id": "pix", "model": "Pixel 8 Pro"},
              "watch": {"device_id": "watch-1", "model": "Galaxy Watch"},
              "desk": {"device_id": "desk-1", "model": "Desk"},
              "face": {"device_id": "face"},
              "laptop": {"device_id": "claude-laptop-twinsnakes", "model": "Claude (laptop, twinsnakes)"},
              "term": {"device_id": "terminal-jarvis", "model": "Desktop terminal"},
              "peer": {"token": "scratch", "name": "Pi Jarvis", "device_id": "peer-pi"}}
    ws = {}
    for k, h in hellos.items():
        ws[k] = await websockets.connect(url)
        await ws[k].send(json.dumps({"type": "hello", **h}))
    await asyncio.sleep(0.3)

    async def drain(t=0.3):
        """{client: (audio frames, jarvis lines, turn_dones)} since last call."""
        out = {}
        for k, w in ws.items():
            if w is None:
                continue
            a, lines, done = 0, [], 0
            try:
                while True:
                    m = await asyncio.wait_for(w.recv(), t)
                    if isinstance(m, bytes):
                        a += 1
                        continue
                    d = json.loads(m)
                    if d["type"] == "line" and d["who"] == "jarvis":
                        lines.append(d["text"])
                    done += d["type"] == "turn_done"
            except asyncio.TimeoutError:
                pass
            out[k] = (a, lines, done)
        return out

    async def turn(who, text, reply, b=None):
        if who:
            await ws[who].send(json.dumps({"type": "text", "text": text}))
            await asyncio.sleep(0.1)
        (b or brain)._client.q.put_nowait(ev(reply))
        await asyncio.sleep(1.0)              # past FLUSH_AFTER
        (b or brain)._client.q.put_nowait(res())
        await asyncio.sleep(0.2)
        return await drain()

    # builds without the face mirror (the Pi's) send the face nothing
    mirror_on = "mirror" in inspect.signature(BrowserBridge.make_sink).parameters

    def only(got, who, text, mirror=True):
        """`who` got the reply's audio, words and turn_done; the face only the
        words (the mirror); nobody else anything."""
        for k, (a, lines, done) in got.items():
            if k == who:
                assert a == 1 and lines == [text] and done == 1, (k, got)
            elif k == "face" and mirror and mirror_on and who not in ("face", "peer"):
                assert a == 0 and lines == [text] and done == 0, (k, got)
            else:
                assert a == 0 and lines == [] and done == 0, (k, got)

    await drain()
    assert br.pin() is None              # nobody has spoken yet: this machine's speakers

    only(await turn("watch", "hi from the watch", "Watch reply."), "watch", "Watch reply.")
    only(await turn("desk", "hi from the desk", "Desk reply."), "desk", "Desk reply.")
    # a helper finishes: to the desk, the last device sir used
    only(await turn(None, "", "Helper done."), "desk", "Helper done.")
    assert open(os.path.join(tmp, ".voice_active_conn")).read().strip() in ("", "desk-1")
    # the laptop Claude and the terminal chat get their own replies, and
    # don't take the background turns
    only(await turn("laptop", "status?", "Laptop reply."), "laptop", "Laptop reply.")
    only(await turn("term", "typed", "Terminal reply."), "term", "Terminal reply.")
    only(await turn(None, "", "Second helper done."), "desk", "Second helper done.")
    # a peer's message goes to its own session and back to the peer only
    await ws["peer"].send(json.dumps({"type": "text", "text": "peer task"}))
    await asyncio.sleep(0.2)
    pb = peers["peer-pi"]
    only(await turn(None, "", "Peer reply.", b=pb), "peer", "Peer reply.")
    only(await turn(None, "", "Third helper done."), "desk", "Third helper done.")
    # the desk unit goes away: the next most recent device still connected
    await ws["desk"].close(); ws["desk"] = None
    await asyncio.sleep(0.2)
    only(await turn(None, "", "Fourth helper done."), "watch", "Fourth helper done.")
    # a device a dedicated session owns (the kitchen mid-recipe) is skipped
    only(await turn("phone", "hi from the phone", "Phone reply."), "phone", "Phone reply.")
    br.owned["pix"] = object()
    only(await turn(None, "", "Fifth helper done."), "watch", "Fifth helper done.")
    br.owned.clear()
    # the watch's reply while the phone is connected: never on the phone
    only(await turn("watch", "again", "Watch again."), "watch", "Watch again.")
    # everyone sir used has gone: nothing plays anywhere
    for k in ("watch", "phone"):
        await ws[k].close(); ws[k] = None
    await asyncio.sleep(0.2)
    got = await turn(None, "", "Nobody here.")
    assert all(a == 0 for a, _, _ in got.values()), got
    # an interrupt's stop still reaches every device
    br.make_recent_sink().stop()
    for k in ("face", "laptop", "term"):
        m = json.loads(await asyncio.wait_for(ws[k].recv(), 1))
        assert m["type"] == "stop", (k, m)
    for w in ws.values():
        if w is not None:
            await w.close()
    await br.stop()
    print("OK", tmp)


asyncio.run(main())
