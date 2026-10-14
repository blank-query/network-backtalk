# Run: BACKTALK_LOG=/tmp/bt-check.log .venv/bin/python tests/check_attachments.py
# Self-check: batch attachments over a real bridge on a spare port, files in
# a temp dir (never the live session or config). Several pictures and files
# wait together and the next question takes them all, in order; the 50 MB
# total is enforced (whole frames and parts, nothing kept past it); one item
# discards by id, image_drop discards all; an older app's whole frames with
# no id still work; the identity frame says "attach".
import asyncio, base64, json, os, sys, tempfile
D = tempfile.mkdtemp(prefix="bt-attach-")
with open(os.path.join(D, "cfg.json"), "w") as f:
    json.dump({"signals_dir": D, "agent_dir": D}, f)
os.environ["BACKTALK_CONFIG"] = os.path.join(D, "cfg.json")
os.environ.setdefault("BACKTALK_LOG", os.path.join(D, "backtalk.log"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import websockets
from backtalk.web import ATTACH_MAX, Attachments, BrowserBridge

PORT = 18797
MB = 2**20


async def frames(ws, t=0.4):
    out = []
    try:
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), t))
            if m["type"] not in ("tasks", "state", "listen", "lines"):
                out.append(m)
    except asyncio.TimeoutError:
        return out


def b64(n, c=b"x"):
    return base64.b64encode(c * n).decode()


async def main():
    br = BrowserBridge({"host": "127.0.0.1", "port": PORT})
    br.attach = Attachments(D)
    asyncio.ensure_future(br.serve())
    await asyncio.sleep(0.3)
    async with websockets.connect(f"ws://127.0.0.1:{PORT}", max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "device_id": "pix", "model": "Pixel 8 Pro"}))
        ident = [m for m in await frames(ws) if m["type"] == "identity"]
        assert ident and ident[0].get("attach") == 50, ident

        # several items, in order: a picture, a file in parts, another picture
        await ws.send(json.dumps({"type": "image", "id": "a", "data": b64(1000, b"\xff")}))
        await ws.send(json.dumps({"type": "file", "id": "b", "name": "notes v2.pdf", "mime": "application/pdf",
                                  "data": b64(3000), "part": 0, "last": False}))
        await ws.send(json.dumps({"type": "file", "id": "b", "name": "notes v2.pdf", "mime": "application/pdf",
                                  "data": b64(2000), "part": 1, "last": True}))
        await ws.send(json.dumps({"type": "image", "id": "c", "data": b64(500)}))
        got = await frames(ws)
        assert got == [{"type": "image_ok", "id": "a"}, {"type": "file_ok", "id": "b", "name": "notes v2.pdf"},
                       {"type": "image_ok", "id": "c"}], got
        held = br.attach.held["pix"]
        assert [i["id"] for i in held] == ["a", "b", "c"] and held[1]["size"] == 5000, held
        assert open(held[1]["path"], "rb").read() == b"x" * 5000

        # discard one by id: the other two stay, in order
        await ws.send(json.dumps({"type": "attach_drop", "id": "b"}))
        await asyncio.sleep(0.2)
        assert [i["id"] for i in br.attach.held["pix"]] == ["a", "c"]

        # the 50 MB total: a part that would pass it is refused and its upload forgotten
        big = ATTACH_MAX - 1500 - 10 * MB
        for n in range(4):     # frames stay under the bridge's 48 MB socket limit
            await ws.send(json.dumps({"type": "file", "id": "d", "name": "big.bin", "data": b64(big // 4),
                                      "part": n, "last": n == 3}))
        assert await frames(ws, 1.5) == [{"type": "file_ok", "id": "d", "name": "big.bin"}]
        await ws.send(json.dumps({"type": "file", "id": "e", "name": "over.bin", "data": b64(6 * MB),
                                  "part": 0, "last": False}))
        await ws.send(json.dumps({"type": "file", "id": "e", "name": "over.bin", "data": b64(6 * MB),
                                  "part": 1, "last": True}))
        got = await frames(ws, 1.5)
        assert len(got) == 1 and got[0]["type"] == "attach_refused" and got[0]["id"] == "e", got
        # (its part 1 then has no upload to join: refused too, quietly kept out)
        assert [i["id"] for i in br.attach.held["pix"]] == ["a", "c", "d"]
        # a whole frame over the cap is refused as well
        await ws.send(json.dumps({"type": "image", "id": "f", "data": b64(11 * MB)}))
        got = await frames(ws, 1.5)
        assert got and got[0]["type"] == "attach_refused" and got[0]["id"] == "f", got
        # ...but one that fits still goes in
        await ws.send(json.dumps({"type": "image", "id": "g", "data": b64(9 * MB)}))
        assert await frames(ws, 1.5) == [{"type": "image_ok", "id": "g"}]
        assert br.attach.total("pix") <= ATTACH_MAX

        # the next question takes them all, in order, and nothing is left
        line = br.attach.take("pix")
        paths = [i for i in line.split() if i.startswith(D)]
        assert line.startswith("[The user shared 4 attachments with this message, in this order;") and len(paths) == 4, line
        assert "1. " in line and "4. " in line and "(unknown type," in line, line
        assert br.attach.take("pix") == ""

        # image_drop discards everything waiting
        await ws.send(json.dumps({"type": "image", "id": "h", "data": b64(10)}))
        await ws.send(json.dumps({"type": "image_drop"}))
        await asyncio.sleep(0.2)
        assert br.attach.take("pix") == ""

    # an older app: whole frames, no ids, acked as before; one image reads as before
    async with websockets.connect(f"ws://127.0.0.1:{PORT}") as ws:
        await ws.send(json.dumps({"type": "hello", "device_id": "old", "model": "Pixel 6"}))
        await frames(ws)
        await ws.send(json.dumps({"type": "image", "data": b64(100)}))
        got = await frames(ws)
        assert got == [{"type": "image_ok", "id": None}], got
        line = br.attach.take("old")
        assert line.startswith("[The user shared an image with this message;") and ". " not in line.split(":")[1][:3], line
        await ws.send(json.dumps({"type": "file", "name": "a.txt", "mime": "text/plain", "data": b64(10)}))
        await ws.send(json.dumps({"type": "image", "data": b64(100)}))
        got = await frames(ws)
        assert got[0] == {"type": "file_ok", "id": None, "name": "a.txt"} and got[1]["type"] == "image_ok", got
        line = br.attach.take("old")
        assert "2 attachments" in line and line.index("a.txt") < line.index(".jpg"), line
        # an older app over the cap: no id to refuse, so nothing comes back and nothing is kept
        br.attach.add("old", b"x" * (45 * MB), "held.bin")
        await ws.send(json.dumps({"type": "file", "name": "huge.bin", "data": b64(6 * MB)}))
        assert await frames(ws, 2) == []
        assert [i["size"] for i in br.attach.held["old"]] == [45 * MB]

    # pruning keeps the newest few files but never one still waiting
    a = Attachments(os.path.join(D, "prune"))
    first = a.add("x", b"1", "keep.txt")
    for n in range(60):
        a.add("y", b"2", f"f{n}.txt")
    a.held["y"] = []
    for n in range(60):
        a.add("z", b"3", f"g{n}.txt")
    assert os.path.exists(first["path"]), "a waiting file was pruned"
    print(f"ok: batch in order, parts, 50 MB cap, discard one and all, older apps, pruning ({D})")


asyncio.run(main())
