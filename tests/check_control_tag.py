# Run: .venv/bin/python tests/check_control_tag.py (config, signals, and log in a temp dir)
# The agent's <<control VERB>> tag, through the real main loop and bridge
# (a scratch amain on a spare port, a fake brain, mouth, ears, and talk key):
# it acts on the device that asked, only once the reply has finished (a
# clear never cuts it off), speaks no confirmation of its own, sends the
# device the timeout switch, and is refused for a peer agent's session or
# a verb it doesn't allow (permissions).
import asyncio, json, os, sys, tempfile, threading
tmp = tempfile.mkdtemp(prefix="bt-control-")
PORT = 18799
with open(os.path.join(tmp, "backtalk.json"), "w") as f:
    json.dump({"agent_dir": tmp, "signals_dir": tmp, "name": "Jarvis", "warmup_ping": False,
               "show_speed": False, "resume_last_session": False,
               "web": {"enabled": True, "host": "127.0.0.1", "port": PORT}}, f)
os.environ.update(BACKTALK_CONFIG=os.path.join(tmp, "backtalk.json"),
                  BACKTALK_LOG=os.path.join(tmp, "backtalk.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import websockets
from backtalk import main as M
from backtalk.mouth import DIRECTION_HOOKS

said, commands, made, _brains = [], [], {}, []


class Mouth:
    speaking = False
    def say(self, text, remote_sink=None): said.append(text)
    def __getattr__(self, n): return lambda *a, **k: None


class Brain:
    def __init__(self, **k):
        self.mouth, self.model, self.turn_active = k.get("mouth"), "fake", False
        self.session = {"turns": 0, "out_tokens": 0, "cost": 0.0}
        self.remote_sink = None
        self.bus = M.signals
        _brains.append(self)
    async def start(self): pass
    async def stop(self): pass
    async def command(self, c): commands.append(c); return ""
    async def context_usage(self): return {}
    def __getattr__(self, n): return lambda *a, **k: None


class Bridge(M.BrowserBridge):
    def __init__(self, cfg):
        super().__init__(cfg)
        made["bridge"] = self


class Key:
    def __init__(self, *a): pass
    def wait_press(self): threading.Event().wait()


M.Mouth, M.WarmBrain, M.BrowserBridge, M.PTTListener = Mouth, Brain, Bridge, Key
class Ears:
    def __init__(self, **k): pass
    def listen_once(self, **k):
        import time; time.sleep(0.2)


M.Ears = Ears
M.warm_ears = M.warm_mouth = lambda: None
M._typed_reader = lambda q: None


async def until(cond, s=3.0):
    for _ in range(int(s / 0.05)):
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


async def run():
    try:
        await _run()
    except BaseException:
        import traceback; traceback.print_exc()
        os._exit(1)


async def _run():
    t = asyncio.ensure_future(M.amain())
    t.add_done_callback(lambda t: t.cancelled() or not t.exception() or print("AMAIN DIED", repr(t.exception())))
    assert await until(lambda: "bridge" in made and M.CFG and _up()), "bridge up"
    frames = []
    ws = await websockets.connect(f"ws://127.0.0.1:{PORT}")
    await ws.send(json.dumps({"type": "hello", "device_id": "phone-1", "model": "Pixel"}))

    async def read():
        async for m in ws:
            if isinstance(m, str):
                frames.append(json.loads(m))
    asyncio.ensure_future(read())
    b = made["bridge"]
    assert await until(lambda: any(c.id == "phone-1" for c in b._conns))
    conn = next(c for c in b._conns if c.id == "phone-1")
    sink, brain, hook = b.make_sink(conn), _brains[0], next(h for h in DIRECTION_HOOKS if h.__name__ == "_control")

    said.clear()     # the greeting
    # hands-free: held while the reply's turn runs, then on, silently
    brain.turn_active = True
    hook(["control hands_free"], sink)
    await asyncio.sleep(0.8)
    assert not conn.listening, "nothing switches mid-reply"
    brain.turn_active = False
    assert await until(lambda: conn.listening), "hands-free on after the reply"
    assert await until(lambda: any(f == {"type": "listen", "on": True, "muted": False} for f in frames))
    assert not said, f"no confirmation of its own: {said}"

    # clear: only after the reply
    brain.turn_active = True
    hook(["control clear"], sink)
    await asyncio.sleep(0.8)
    assert "/clear" not in commands
    brain.turn_active = False
    assert await until(lambda: "/clear" in commands)

    # effort, written to the scratch config
    hook(["control effort high"], sink)
    assert await until(lambda: "/effort high" in commands)
    assert json.load(open(os.path.join(tmp, "backtalk.json")))["effort"] == "high"

    # the timeout switch: kept for the device, and sent to it
    hook(["control timeout_off"], sink)
    assert await until(lambda: not b.times_out(conn))
    assert await until(lambda: {"type": "hands_free_timeout", "on": False} in frames)
    await ws.send(json.dumps({"type": "caps", "caps": {"hf_timeout": True}}))   # the app's switch
    assert await until(lambda: b.times_out(conn))

    # push to talk, pause
    hook(["control pause"], sink)
    assert await until(lambda: conn.listen_muted)
    hook(["control push_to_talk"], sink)
    assert await until(lambda: not conn.listening)

    # the idle timeout itself honours the switch
    M.CFG["hands_free_timeout_s"] = 1
    hook(["control timeout_off"], sink)
    hook(["control hands_free"], sink)
    assert await until(lambda: conn.listening)
    await asyncio.sleep(2.5)
    assert conn.listening, "switched off: never times out"
    hook(["control timeout_on"], sink)
    assert await until(lambda: not conn.listening, 4), "switched on: times out"
    assert said == ["Hands-free off."], said
    said.clear()

    # refused: permissions, and a peer agent's session
    n = len(commands)
    hook(["control noask", "control stop_asking_for_permission"], sink)
    conn.peer = "Pi Jarvis"
    hook(["control clear"], sink)
    await asyncio.sleep(0.8)
    conn.peer = None
    assert len(commands) == n and not M._AUTOAPPROVE["on"]
    log = open(os.path.join(tmp, "backtalk.log")).read()
    assert log.count("control tag refused") == 3, log[-800:]
    assert not said, said
    print("control tag ok")
    os._exit(0)


def _up():
    import socket
    try:
        socket.create_connection(("127.0.0.1", PORT), 0.2).close()
        return True
    except OSError:
        return False


try:
    asyncio.run(asyncio.wait_for(run(), 30))
except BaseException as e:
    import traceback; traceback.print_exc()
    os._exit(1)
