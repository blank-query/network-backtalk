# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_show_file.py
# Self-check: text stays a document card, anything else becomes a file card
# line, and file_frames carries it back whole in 256 KB pieces.
import base64, json, os, re, sys, tempfile
from urllib.parse import unquote
D = tempfile.mkdtemp()
with open(os.path.join(D, "cfg.json"), "w") as f:
    json.dump({"signals_dir": D}, f)
os.environ["BACKTALK_CONFIG"] = os.path.join(D, "cfg.json")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk import web

note, empty, pdf = (os.path.join(D, n) for n in ("note.md", "empty.txt", "a [report].pdf"))
open(note, "w", encoding="utf-8").write("# Hi\n" + "é" * 5000)     # a 2-byte character cut at 8 KB
open(empty, "w").close()
data = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + os.urandom(600_000)
open(pdf, "wb").write(data)
assert web.is_text(note) and web.is_text(empty) and not web.is_text(pdf)

m = re.fullmatch(r"\[file: (.+)\]\(jarvis-file:([^)#]+)#(\d+)\)", web.file_card(pdf))
assert m and m[1] == "a report.pdf" and unquote(m[2]) == pdf and int(m[3]) == len(data), m

frames = list(web.file_frames(pdf))
assert len(frames) == 3 and [f["last"] for f in frames] == [False, False, True]
assert b"".join(base64.b64decode(f["data"]) for f in frames) == data
assert [f["last"] for f in web.file_frames(empty)] == [True]

big = os.path.join(D, "big.bin")
with open(big, "wb") as f:
    f.truncate(web.FILE_MAX + 1)
try:
    web.file_card(big); raise SystemExit("over the cap was accepted")
except ValueError:
    pass
print("ok: text vs file, card line, 3 chunks round trip, empty file, size cap")
