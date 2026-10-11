# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_show_image.py
# Self-check: a <<show>> picture becomes one markdown data-URL line; a small
# one goes as it is, a big one is shrunk by ffmpeg to a JPEG of at most
# 1280 px and stays under the frame cap.
import base64, json, os, re, subprocess, sys, tempfile
D = tempfile.mkdtemp()
with open(os.path.join(D, "cfg.json"), "w") as f:
    json.dump({"signals_dir": D}, f)
os.environ["BACKTALK_CONFIG"] = os.path.join(D, "cfg.json")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtalk import web

small, big = os.path.join(D, "small.png"), os.path.join(D, "big shot.png")
subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=200x100", "-frames:v", "1", small], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "nullsrc=s=1568x1690,geq=random(1)*255:128:128",
                "-frames:v", "1", big], check=True)          # noise: about 5 MB as PNG
assert os.path.getsize(big) > web.IMAGE_KEEP

md = web.image_card(small)
m = re.fullmatch(r"!\[small\.png\]\(data:image/png;base64,([A-Za-z0-9+/=]+)\)", md)
assert m and base64.b64decode(m[1]) == open(small, "rb").read(), md[:80]

md = web.image_card(big)
m = re.fullmatch(r"!\[big shot\.png\]\(data:image/jpeg;base64,([A-Za-z0-9+/=]+)\)", md)
assert m and len(md) < web.IMAGE_MAX + 100, md[:80]
p = os.path.join(D, "out.jpg"); open(p, "wb").write(base64.b64decode(m[1]))
w, h = map(int, subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", p],
                                capture_output=True, text=True).stdout.strip().split(","))
assert max(w, h) <= web.IMAGE_SIDE, (w, h)
print(f"ok: small as-is, big {os.path.getsize(big) // 1024} KB -> {w}x{h}, {len(md) // 1024} KB frame")
