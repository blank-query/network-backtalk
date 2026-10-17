# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_speakable.py
# Picture embeds, tags, data URLs, and base64 runs are never spoken; an
# image-only line still carries its directions; the terminal text is untouched.
import os, queue, sys, tempfile, types, json
D = tempfile.mkdtemp()
with open(os.path.join(D, "cfg.json"), "w") as f:
    json.dump({"signals_dir": D}, f)
os.environ["BACKTALK_CONFIG"] = os.path.join(D, "cfg.json")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk.mouth import Mouth, speakable
from backtalk.brain import _sentence_end

# the 2026-10-11 line Pi Jarvis read aloud
assert speakable("![Pi desktop right now](.backtalk/shots/pi-desktop-now.png)") == ""
assert speakable("Here it is, sir. ![a. b](x.png) Enjoy.") == "Here it is, sir. Enjoy."
assert speakable("See ![shot](data:image/jpeg;base64,/9j/4AAQSkZJRg==) there.") == "See there."
assert speakable("raw data:image/png;base64,iVBORw0KGgo= end") == "raw end"
assert speakable("blob " + "QUJD" * 20 + " done") == "blob done"
assert speakable("Hi <<show x.png>> there.") == "Hi there."
assert speakable("A normal sentence, with a URL example.com/a/b.") == "A normal sentence, with a URL example.com/a/b."

# markdown symbols are never read out (2026-10-17: "asterisk asterisk sauce")
assert speakable("**Sauce**") == "Sauce"
assert speakable("## Ingredients") == "Ingredients"
assert speakable("*a* _b_ __c__") == "a b c"
assert speakable("Set snake_case_name now.") == "Set snake_case_name now."
assert speakable("5 * 3 and 2*4") == "5 times 3 and 2 times 4"
assert speakable("- **Rice:** Store brand.\n* Glaze: brown sugar.\n+ more") == "Rice: Store brand. Glaze: brown sugar. more"
assert speakable("Use `jarvis-update` then ```python x```") == "Use jarvis-update then python x"
assert speakable("Bay #5, -5 degrees, eggs - two.") == "Bay #5, -5 degrees, eggs - two."
assert speakable("**For next time:** - Get a press.") == "For next time: - Get a press."

m = types.SimpleNamespace(_q=queue.Queue(), turn=None)
Mouth.say_chunk(m, "![Pi desktop](shot.png)", ["show shot.png"], None)
assert m._q.get_nowait()[:3] == ("", ["show shot.png"], None)
Mouth.say(m, "One. ![x. y](z.png) Two.")
assert [m._q.get_nowait()[0] for _ in range(2)] == ["One.", "Two."] and m._q.empty()

# the brain's splitter does not break inside a picture's alt text
buf = "![Pi desk. Now](a.png) Next. "
assert buf[:_sentence_end(buf).start()] == "![Pi desk. Now](a.png) Next."
print("OK")
