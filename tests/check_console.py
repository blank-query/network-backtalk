# Run: .venv/bin/python tests/check_console.py (config and log in a temp dir)
# The voice console's phrase matcher takes what Whisper, Moonshine, and the
# phones actually write down (the variants below are from the desktop's and
# the Pi's logs, 2026-10-04 to 10-12, where sir was refused), and still
# ignores ordinary sentences. The <<control>> tag: what it may do, never
# permissions; the per-device hands-free timeout switch.
import asyncio, json, os, sys, tempfile
tmp = tempfile.mkdtemp(prefix="bt-console-")
with open(os.path.join(tmp, "backtalk.json"), "w") as f:
    json.dump({"agent_dir": tmp, "signals_dir": tmp, "name": "Jarvis"}, f)
os.environ.update(BACKTALK_CONFIG=os.path.join(tmp, "backtalk.json"),
                  BACKTALK_LOG=os.path.join(tmp, "backtalk.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk.brain import _DIRECTION_TAG
from backtalk.config import DISCIPLINE
from backtalk.main import CONSOLE_VERBS, CONTROL_VERBS, console_match, trailing_mic_verb, wake_text
from backtalk.web import BrowserBridge

for said, want in [
        ("Jarvis, go hands-free.", "micopen"), ("Jarvis go hands free", "micopen"),
        ("Jarvis. Go hands-free!", "micopen"), ("jarvis, go hands-free mode", "micopen"),
        ("Jarvis, Go hands-free", "micopen"), ("JARVIS GO HANDS FREE", "micopen"),
        ("Okay Jarvis, go hands free please.", "micopen"), ("Jarvis, hands-free mode.", "micopen"),
        ("Jarvis, go, push to talk.", "micptt"), ("Jarvis pushed to talk mode", "micptt"),
        ("Jarvis. Push to talk mode Whoa.", "micptt"), ("Jarvis pushed to talk my...", "micptt"),
        ("Jarvis, push to talk, most.", "micptt"), ("Jarvis pushed a talk mode.", "micptt"),
        ("Jarvis. Jarvis. Jarvis. Jarvis. Push to talk mode", "micptt"),
        ("Travis stop listening", "micmute"), ("Jarvis Stop listening.", "micmute"),
        ("Javi, start listening.", "micopen"), ("Jarvis, set effort to low", "effort:low"),
        ("Jarvis, set the effort to high.", "effort:high"), ("Jarvis, effort max", "effort:max"),
        ("Jarvis, set effort to xhigh", "effort:xhigh"), ("Jarvis, clear the session.", "clear"),
        ("Jarvis, compact the session now.", "compact"), ("Jarvis, usage report.", "usage"),
        ("Jarvis, switch to the deep model.", "deep"), ("Jarvis, back to the fast model", "fast"),
        ("Jarvis, turn off the hands-free timeout.", "timeout:off"),
        ("Jarvis, hands free timeout on", "timeout:on"),
        ("Jarvis, stop asking for permission.", "noask"), ("Jarvis, stop.", "stop"),
        ("Jarvis, abort.", "abort"),
        # ordinary speech never flips anything
        ("Go hands free.", None), ("The old hands free Jarvis.", None),
        ("You're supposed to stay hands-free", None), ("Jarvis, push to talk mode is broken", None),
        ("Jarvis, mute the TV", None), ("Jarvis, pause the music", None),
        ("Jarvis, stop the timer", None), ("Jarvis, start listening to this song", None),
        ("Jarvis, clear the session history please and the notes", None),
        ("Jarvis, clear the sessions log", None), ("Jarvis, set effort to high and research it", None),
        ("Harvest go hands free", None), ("Drivers push to talk mode", None),
        ("Jarvis Gluhuis to talk.", None), ("Jarvis", None), ("", None), ("abort", None)]:
    got = console_match(said)
    assert got == want, (said, got, want)
# a listening command ending a longer utterance, and after the wake word
assert trailing_mic_verb("That worked. Jarvis, pause.") == ("micmute", "That worked.")
assert trailing_mic_verb("That worked. Jarvis, go hands-free mode.")[0] == "micopen"
assert wake_text("go hands-free") == "Jarvis, go hands-free"

# ---- the <<control>> tag
handled = set(CONSOLE_VERBS) | {"usage", "deep", "fast", "compact", "clear"}
assert set(CONTROL_VERBS.values()) <= handled, set(CONTROL_VERBS.values()) - handled
assert not {"noask", "ask", "noask:confirmed", "abort", "stop"} & set(CONTROL_VERBS.values()), \
    "permissions and abort stay spoken phrases only"
for key in CONTROL_VERBS:
    if not key.startswith("effort_") or key == "effort_low":
        assert f"<<control {key}>>" in DISCIPLINE, key
assert "never tell the person to say an exact phrase" in DISCIPLINE
assert _DIRECTION_TAG.findall("Hands-free on, sir. <<control hands_free>>") == ["control hands_free"]


def key(d):   # as main's _control reads a tag
    return "_".join(d[8:].lower().replace("-", " ").split())
assert CONTROL_VERBS[key("control effort high")] == "effort:high"
assert CONTROL_VERBS[key("control hands-free")] == "micopen"
assert key("control noask") not in CONTROL_VERBS

# ---- the per-device timeout switch (web.py): the caps' "hf_timeout"
class WS:
    sent = []
    async def send(self, t): WS.sent.append(json.loads(t))
class C:
    id, ws, active = "dev-1", WS(), 0.0


async def run():
    b, c = BrowserBridge({}), C()
    b.devices_file = os.path.join(tmp, "devices.json")
    b.saw(c, "Pixel", {"role": "full", "actions": ["notify"]})
    assert b.times_out(c), "times out by default"
    b.set_hf_timeout(c, False)
    await asyncio.sleep(0)
    assert not b.times_out(c) and WS.sent[-1] == {"type": "hands_free_timeout", "on": False}
    assert b.devices()["dev-1"]["caps"]["actions"] == ["notify"], "the rest of the caps kept"
    b.saw(c, None, {"role": "full", "hf_timeout": True})    # the app's switch, sent as caps
    assert b.times_out(c)
    b.saw(c, None, {"role": "full", "hf_timeout": False})
    assert not b.times_out(c)
asyncio.run(run())
print("OK")
