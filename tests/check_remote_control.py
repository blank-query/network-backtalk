# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_remote_control.py
# Self-check: config remote_control. Off sends nothing; true sends the CLI's
# remote_control control request named peer_name; a string names it that; a
# dedicated session (persist=False) never sends it; a failure is logged and
# never raised (the session must still start).
import asyncio, os, sys, tempfile
D = tempfile.mkdtemp()
os.environ["BACKTALK_CONFIG"] = os.path.join(D, "none.json")
os.environ.setdefault("BACKTALK_LOG", os.path.join(D, "bt.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from types import SimpleNamespace
from backtalk.brain import WarmBrain
from backtalk.config import CFG

sent = []


async def ok(req, timeout):
    sent.append((req, timeout))
    return {"session_url": "https://example/session"}


async def boom(req, timeout):
    raise TimeoutError("no answer")


b = WarmBrain()
b._client = SimpleNamespace(_query=SimpleNamespace(_send_control_request=ok))
assert CFG["remote_control"] is False
asyncio.run(b._remote_control())
assert sent == []                                    # off by default: nothing sent

CFG["remote_control"], CFG["peer_name"] = True, "Desktop Jarvis"
asyncio.run(b._remote_control())
assert sent.pop() == ({"subtype": "remote_control", "enabled": True,
                       "name": "Desktop Jarvis"}, 30)

CFG["remote_control"] = "Kitchen"
asyncio.run(b._remote_control())
assert sent.pop()[0]["name"] == "Kitchen"

d = WarmBrain(persist=False)                         # a dedicated session: never
d._client = b._client
asyncio.run(d._remote_control())
assert sent == []

b._client._query._send_control_request = boom
asyncio.run(b._remote_control())                     # logged, not raised
with open(os.environ["BACKTALK_LOG"]) as f:
    log = f.read()
assert "remote control on as 'Desktop Jarvis': https://example/session" in log
assert "remote control failed: TimeoutError('no answer')" in log
print("ok")
