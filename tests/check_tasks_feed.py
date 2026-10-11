# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_tasks_feed.py
# Self-check: the assistant picker's backend. The session to-do CLI;
# running tasks with what they're doing; a device token lets a device in
# where require_token refuses it without one (wrong one: 4401); every
# device gets who this is and the task list on hello, and the list again
# when it changes; cooking steps; pushed face state; a peer passes a grant
# to a connected device by name; revoking a token locks it out again.
import asyncio, hashlib, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import websockets
from claude_agent_sdk import SystemMessage, TaskStartedMessage
from backtalk import brain as B, todo, grant
from backtalk.web import BrowserBridge

D = tempfile.mkdtemp()
TODO, TOK = os.path.join(D, "todo.json"), os.path.join(D, "tokens.json")

# ---- the to-do CLI
todo.run(TODO, ["add", "write the panel"])
todo.run(TODO, ["wait", "pick a frame color"])
todo.run(TODO, ["start", "1"])
out = todo.run(TODO, ["add", "drop me"])
assert "1. [IN PROGRESS] write the panel" in out and "2. [WAITING ON SIR]" in out \
    and "3. [NOT STARTED] drop me" in out, out
todo.run(TODO, ["done", "3"])
assert "drop me" not in todo.run(TODO, [])


# ---- task descriptions from the brain
class Bus:
    def __getattr__(s, n): return lambda *a, **k: None
class Mouth:
    speaking, busy = False, (lambda s: False)
    def say_chunk(s, *a): pass
class Client:
    def __init__(s): s.q = asyncio.Queue()
    async def query(s, u): pass
    def receive_messages(s):
        async def gen():
            while True: yield await s.q.get()
        return gen()


async def brain_check():
    b = B.WarmBrain(mouth=Mouth(), bus=Bus())
    b._client = c = Client(); b._start_reader()
    c.q.put_nowait(TaskStartedMessage(subtype="task_started", data={}, task_id="a",
                                      description="Build the watch", uuid="u", session_id="s"))
    await asyncio.sleep(0.05)
    assert b.task_list() == [{"text": "Build the watch"}], b.task_list()
    c.q.put_nowait(SystemMessage(subtype="background_tasks_changed", data={"tasks": [
        {"task_id": "a"}, {"task_id": "b", "description": "npm run dev"}]}))
    await asyncio.sleep(0.05)
    assert b.task_list() == [{"text": "Build the watch"}, {"text": "npm run dev"}], b.task_list()
    b._reader_task.cancel()
    return b


async def recv(ws, kind, t=3):
    while True:
        m = await asyncio.wait_for(ws.recv(), t)
        if isinstance(m, str) and json.loads(m).get("type") == kind:
            return json.loads(m)


async def main():
    b = await brain_check()
    tok = "device-secret"
    with open(TOK, "w") as f:
        json.dump({hashlib.sha256(tok.encode()).hexdigest(): {"device": "Pixel 8 Pro"}}, f)
    os.makedirs(os.path.join(D, "bus"))
    with open(os.path.join(D, "bus", ".voice_state"), "w") as f:
        f.write("thinking")

    # "the desktop": with require_token, refuses anyone off this machine
    # without a token (the check below makes loopback look remote)
    br = BrowserBridge({"host": "127.0.0.1", "port": 18794, "require_token": True})
    br._token = "peer-secret"
    br.tokens_file, br.todo_file, br.signals_dir = TOK, TODO, os.path.join(D, "bus")
    br.task_source = b.task_list
    br.identity = {"type": "identity", "name": "Desktop Jarvis", "color": "#d8dde3", "face": "board"}
    switched = []
    br.on_switch = lambda conn: switched.append(conn.id)
    br.devices_file = os.path.join(D, "devices.json")
    srv = asyncio.ensure_future(br.serve())
    await asyncio.sleep(0.3)
    # the bridge treats loopback as local: make it act remote for this check
    import backtalk.web as W
    import ipaddress, types
    W.ipaddress = types.SimpleNamespace(ip_address=lambda a: ipaddress.ip_address("10.0.0.9"))
    url = "ws://127.0.0.1:18794"

    async def refused(hello):
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps(hello))
            try:
                await asyncio.wait_for(ws.recv(), 3)
            except websockets.exceptions.ConnectionClosed as e:
                return e.rcvd.code
        return None
    assert await refused({"type": "hello", "device_id": "x"}) == 4401
    assert await refused({"type": "hello", "device_id": "x", "device_token": "nope"}) == 4401

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "hello", "device_id": "pix", "device_token": tok,
                                  "switched": True, "push": True}))
        idn = await recv(ws, "identity")
        assert idn["name"] == "Desktop Jarvis" and idn["color"] == "#d8dde3", idn
        t = await recv(ws, "tasks")
        assert t["running"] == [{"text": "write the panel"}, {"text": "Build the watch"},
                                {"text": "npm run dev"}], t
        assert t["waiting"] == [{"text": "pick a frame color"}] and t["todo"] == [], t
        assert switched == ["pix"], switched
        st = await recv(ws, "state")
        assert st["state"] == "thinking", st
        todo.run(TODO, ["add", "later thing"])
        t = await recv(ws, "tasks")
        assert t["todo"] == [{"text": "later thing"}], t
        br.set_cook("pix", ["Boil water", "Pasta in"], 1)
        ck = await recv(ws, "cook")
        assert ck["steps"] == ["Boil water", "Pasta in"] and ck["current"] == 1, ck

        # a peer passes a grant to this connected device, by name
        with open(br.devices_file, "w") as f:
            json.dump({"pix": {"name": "Pixel 8 Pro"}}, f)
        async with websockets.connect(url) as peer:
            await peer.send(json.dumps({"type": "hello", "device_id": "peer-x", "name": "Friday",
                                        "token": "peer-secret"}))
            await recv(peer, "peer_ok")
            g = {"type": "grant", "assistant": {"id": "friday"}, "token": "t"}
            await peer.send(json.dumps({"type": "deliver", "device": "Pixel 8 Pro", "frame": g}))
            assert (await recv(peer, "delivered"))["ok"] is True
            assert (await recv(ws, "grant"))["token"] == "t"
            await peer.send(json.dumps({"type": "deliver", "device": "Kitchen", "frame": g}))
            assert (await recv(peer, "delivered"))["ok"] is False
            await peer.send(json.dumps({"type": "deliver", "device": "Pixel 8 Pro",
                                        "frame": {"type": "phone", "do": "call"}}))
            assert (await recv(peer, "delivered"))["ok"] is False, "only grants pass"

    # revoked: the same token is refused at the next connect
    cfg = {"agent_dir": D}
    os.makedirs(os.path.join(D, ".backtalk"), exist_ok=True)
    os.replace(TOK, grant.tokens_path(cfg))
    br.tokens_file = grant.tokens_path(cfg)
    assert "revoked 1" in grant.revoke(cfg, "Pixel 8 Pro")
    assert await refused({"type": "hello", "device_id": "pix", "device_token": tok}) == 4401
    a = grant.assistant({"name": "Jarvis", "peer_name": "Desktop Jarvis", "lan_url": "ws://h:8792"})
    assert a["id"] == "desktop-jarvis" and a["url"] == "ws://h:8792", a
    srv.cancel()
    print("OK")

asyncio.run(main())
