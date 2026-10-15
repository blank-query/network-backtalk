# Run: .venv/bin/python tests/check_idle_clear.py (config, signals, and log in a temp dir)
# Self-check: the idle clear and the cook summary handoff, with a fake brain.
# Blockers (a turn in flight, a helper, a dedicated session, a pending
# confirm, a reply playing) re-arm the timer; after the silence a save turn
# goes out, then /clear, and what it saved rides on the next message as the
# resume question, once. Speech during the save, HOLD, or a failed save: no
# clear. Nothing new since the last clear: no second clear. A cook session
# ending hands its summary to the main session's next turn.
import asyncio, json, os, sys, tempfile, time
tmp = tempfile.mkdtemp(prefix="bt-idle-")
with open(os.path.join(tmp, "backtalk.json"), "w") as f:
    json.dump({"agent_dir": tmp, "signals_dir": tmp}, f)
os.environ.update(BACKTALK_CONFIG=os.path.join(tmp, "backtalk.json"),
                  BACKTALK_LOG=os.path.join(tmp, "backtalk.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk import main as M
from backtalk.config import CFG

assert CFG["idle_clear_minutes"] == 0 and CFG["cook_fresh_session"] is False, "off by default"


class Mouth:
    speaking = False


class Brain:
    def __init__(self, reply="nothing"):
        self.turn_active, self._ask_queue, self._active_tasks = False, [], set()
        self.mouth, self.reply, self.sent, self.asked = Mouth(), reply, [], []
        self.during = None    # runs while the save turn is out (someone speaking)

    async def capture(self, text, count_turn=True, timeout=None):
        self.sent.append(text)
        if self.during:
            self.during()
        return self.reply

    async def command(self, cmd):
        self.sent.append(cmd)
        return ""

    def clear_tasks(self):
        pass

    def ask(self, text, remote_sink=None):
        self.asked.append((text, remote_sink))


def run(c):
    return asyncio.run(c)


def blocker(b, sessions=None, dedicated=None, **kw):
    return lambda: M.idle_blocker(b, sessions or {}, dedicated or {}, **kw)


old = time.monotonic() - 31 * 60

# ---- blockers re-arm the timer and never clear
b = Brain()
for setup, why in [(lambda: setattr(b, "turn_active", True), "a turn in flight"),
                   (lambda: b._ask_queue.append(1), "a turn in flight"),
                   (lambda: b._active_tasks.add("t1"), "a helper running"),
                   (lambda: setattr(b.mouth, "speaking", True), "a reply playing")]:
    b.turn_active, b._ask_queue, b._active_tasks, b.mouth.speaking = False, [], set(), False
    setup()
    st = {"last": old, "dirty": True}
    assert run(M.idle_clear(b, st, 30, blocker(b))) == why
    assert st["last"] > old + 60 and not b.sent, "blocked: re-armed, nothing sent"
b = Brain()
st = {"last": old, "dirty": True}
assert run(M.idle_clear(b, st, 30, blocker(b, dedicated={"k": "cook with me"}))) == "a dedicated session open"
class Peer: turn_active = True
assert M.idle_blocker(b, {"p": Peer()}, {}) == "a peer turn in flight"
assert M.idle_blocker(b, {}, {}, abort_open=True) == "a confirmation pending"
M._CONFIRM.update(verb="noask", at=time.monotonic())
assert M.idle_blocker(b, {}, {}) == "a confirmation pending"
M._CONFIRM.update(verb=None)
assert M.idle_blocker(b, {}, {}, capturing=True) == "someone talking"
assert M.idle_blocker(b, {}, {}) is None

# ---- not long enough yet: nothing
st = {"last": time.monotonic() - 29 * 60, "dirty": True}
assert run(M.idle_clear(b, st, 30, blocker(b))) is None and not b.sent

# ---- the clear: save turn, then /clear, then the marker rides on the next message once
b = Brain("Saved a test reminder to the task list.")
st = {"last": old, "dirty": True}
assert run(M.idle_clear(b, st, 30, blocker(b))) == "cleared"
assert b.sent[0].startswith("[system] Idle clear") and "30 minutes" in b.sent[0]
assert b.sent[1] == "/clear" and st["dirty"] is False
r = M.take_idle_marker()
assert r and "test reminder" in r and "whether to resume" in r
assert M.take_idle_marker() is None, "asked once"
# nothing new since: no second clear, however long the silence
st["last"] = old
assert run(M.idle_clear(b, st, 30, blocker(b))) is None and len(b.sent) == 2

# ---- nothing saved: clears, no resume question
for reply in ["Nothing.", "Nothing to save."]:
    b = Brain(reply)
    assert run(M.idle_clear(b, {"last": old, "dirty": True}, 30, blocker(b))) == "cleared"
    assert b.sent[-1] == "/clear" and M.take_idle_marker() is None, reply

# ---- the main session's saved id goes too, so a restart starts fresh, not pre-clear
open(M.SESSION_FILE, "w").write("abc123")
b = Brain("nothing")
b._persist = True
assert run(M.idle_clear(b, {"last": old, "dirty": True}, 30, blocker(b))) == "cleared"
assert not os.path.exists(M.SESSION_FILE)

# ---- HOLD, a failed save, and speech during the save: no clear, re-armed
for reply, want in [("HOLD", "hold"), ("error: the command timed out", "save failed"), ("", "save failed")]:
    b = Brain(reply)
    st = {"last": old, "dirty": True}
    assert run(M.idle_clear(b, st, 30, blocker(b))) == want, reply
    assert "/clear" not in b.sent and st["last"] > old + 60
b = Brain("nothing")
st = {"last": old, "dirty": True}
b.during = lambda: st.update(last=time.monotonic(), dirty=True)     # handle() ran
assert run(M.idle_clear(b, st, 30, blocker(b))) == "interrupted" and "/clear" not in b.sent
b = Brain("nothing")
b.during = lambda: setattr(b, "turn_active", True)                  # a queued ask went out
assert run(M.idle_clear(b, {"last": old, "dirty": True}, 30, blocker(b))) == "interrupted"

# ---- the cook summary handoff
cook, main = Brain("Made a test dish; swapped one ingredient."), Brain()
run(M.cook_handoff(cook, main, "Kitchen", "SINK"))
assert cook.sent[0].startswith("[system] This cooking session is over")
(text, sink), = main.asked
assert sink == "SINK" and "Kitchen" in text and "swapped one ingredient" in text and "rate" in text
cook, main = Brain("error: the command timed out"), Brain()
run(M.cook_handoff(cook, main, "Kitchen", None))
assert "couldn't write one" in main.asked[0][0]
print("check_idle_clear: ok")
