# backtalk: talk to your Claude Code agent out loud.
# Copyright (C) 2026 Jared Rhodenizer
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""THE BROWSER BRIDGE: a second push-to-talk, a click/tap on the face in
ai-visualizer instead of (or alongside) the hold-to-talk key.

This module ONLY moves bytes and press/release events over a WebSocket.
It deliberately knows nothing about ears.transcribe(), handle(), or
_MIC, main.py owns all of that, exactly as it already does for the
local key and the open mic, so there is exactly one place that
interrupts a reply and transitions session state. Treat a browser
press as another input source feeding the SAME turn-handling path, not
a parallel reimplementation of it.

Wire protocol, deliberately tiny:
  text frame  {"type": "hello", "device_id": ...}  browser -> server,
                                             first message, sent right
                                             after connecting: the
                                             browser's own persistent
                                             token (see core.js's
                                             DEVICE_ID), used for
                                             Conn.id and per-device
                                             routing.
                                             An optional "model" (the
                                             app's phone model) names a
                                             new device; see saw().
  THE THREE CONTROLS, the same on every client (the bridge protocol):
  text frame  {"type": "press"}             client -> server: talk. Never
                                             interrupts: the client pauses
                                             its own playback (buffering
                                             what keeps arriving) until its
                                             capture ends, then resumes;
                                             the words queue behind the turn
  text frame  {"type": "interrupt"}         client -> server: a tap on
                                             Interrupt. The voice stops and
                                             the rest of that reply is
                                             dropped ("stop" back); helpers
                                             and tools keep running
  text frame  {"type": "abort"}             client -> server: Interrupt
                                             held ~2 s (or "<name>, abort"
                                             spoken). As interrupt, then the
                                             running background tasks are
                                             read back and the next words
                                             from this device pick what
                                             stops ("everything", a number
                                             or a name, "never mind")
  text frame  {"type": "interrupt_press"}   browser -> server (older
                                             clients' Interrupt button:
                                             interrupt, THEN record)
  text frame  {"type": "release"}           browser -> server (with
                                             "text": the phone's own
                                             transcript of the press, used
                                             instead of transcribing the
                                             audio, which still streams as
                                             the fallback and voiceprint)
  binary      <uint32 LE rate><int16 LE PCM...>   either direction
  text frame  {"type": "reply_done"}        server -> browser
  text frame  {"type": "stop"}              server -> browser (an
                                             interrupt: discard every
                                             scheduled-but-unplayed
                                             chunk already sent)
  text frame  {"type": "unmute"}            browser -> server: a click
                                             while paused ("stop
                                             listening"); hands-free
                                             comes back
  text frame  {"type": "hands_free",        browser -> server: switch
               "on": b, "muted": b}          hands-free on, paused, or off
                                             for this tab, silently
  text frame  {"type": "image", "data": b64}  client -> server: a shared
                                             JPEG (the app's share
                                             target); acked with
                                             {"type": "image_ok"}, and
                                             {"type": "image_used"} once
                                             it rides along with a
                                             question
  text frame  {"type": "image_drop"}        client -> server: discard the
                                             pictures and files shared
                                             since its last question
  text frame  {"type": "file", "name": ...,   client -> server: any other
               "mime": ..., "data": b64}       shared file (share sheet or
                                             the terminal's +); acked with
                                             {"type": "file_ok", "name"},
                                             then rides along with the
                                             next question like an image
  text frame  {"type": "phone", "do": ...}  server -> client: a command for
                                             the device that asked (the
                                             agent's <<phone {...}>> tag;
                                             see mouth.py)
  text frame  {"type": "phone_result",      client -> server: what came of
               "text": ...}                  it, when the agent needs to
                                             know (a failure, a lookup);
                                             asked as that device's turn
  text frame  {"type": "text", "text": ...}  client -> server: a typed
                                             question (the face's
                                             terminal), queued like a tap;
                                             with "spoken": true, words the
                                             phone transcribed itself (on-
                                             device push to talk): treated
                                             as speech, not typing
  text frame  {"type": "line", "who":       server -> client: the
               "you"|"jarvis", "text": ...}  conversation as text, this
                                             device's turns only (a
                                             remote device's also go
                                             to this machine's face:
                                             a loopback hello with no
                                             "model");
                                             {"type": "lines", "lines":
                                             [...]} replays the last 60
                                             on hello. A line with
                                             "show": {title, path} is a
                                             card's reopen button; the
                                             client sends {"type":
                                             "reopen", "path": ...} and
                                             gets the file's current
                                             contents as a "show";
                                             "show": {time} is a
                                             reply's timing tag,
                                             shown dim, not spoken
  text frame  {"type": "call", "on": b,     server -> client: an intercom
               "with": name}                 call started or ended. While
                                             on, the client streams its mic
                                             (call-mode echo cancellation)
                                             and plays what arrives; the
                                             bridge relays the frames to
                                             the other end, untranscribed
  text frame  {"type": "app_update",        server -> client: a newer app
               "code": N}                    waits (the hello's "version" was
                                             older); {"type": "app_get"} back
                                             asks for it, and it comes as
                                             {"type": "app_chunk", "data":
                                             base64, "last": b} frames
  text frame  {"type": "file_get",          client -> server: a <<show>>
               "path": ...}                  file card's file (only one shown
                                             on that device), as {"type":
                                             "file_chunk", "path", "data":
                                             base64, "last": b} frames of
                                             256 KB (or one with "error")
  text frame  {"type": "hangup"}            client -> server: end the call
                                             (so does either end
                                             disconnecting, or a press on a
                                             device no session owns; on an
                                             owned one a press talks to its
                                             agent, muted to the far end)
  text frame  {"type": "turn_done"}         server -> client: the agent's
                                             turn for this device is over
                                             (sent even for a text-only
                                             reply, which has no reply_done)
  DEVICE TOKENS: a hello with "device_token" (issued to one device by
  `python -m backtalk.grant`, kept here only as a hash) lets that device
  in when require_token is on; a wrong one closes it (4401, maybe
  transient: the device keeps it), a revoked one (grant.py --revoke)
  with 4403 "revoked", the only close that makes a device forget it. Its hello
  may carry "switched": true (the person just picked this assistant: it
  says who it is) and "push": true (no face server to poll: the bridge
  pushes {"type": "state", ...} as it changes).
  text frame  {"type": "identity", "name",  server -> client, after every
               "color", "face", "hues",      hello: who this assistant is;
               "controls": 1}                "controls": it takes interrupt
                                             and abort (older bridges: no
                                             key, clients use interrupt_press)
  text frame  {"type": "tasks", "waiting":   server -> client, on hello and
               [...], "running": [...],      every change: the session to-do
               "review": [...], "todo": [...], list (backtalk.todo, or the
               "done": [...]}                todo_txt file) plus the running
                                             background tasks, each {"text"};
                                             "review" (finished, awaiting
                                             review) and "done" (accepted)
                                             only from todo_txt; "background":
                                             how many of "running" are
                                             background tasks (the rest are
                                             to-do items being worked)
  text frame  {"type": "cook", "steps":     server -> client: a cooking
               [...], "current": n}          session's steps (<<steps>>);
                                             no steps = cooking is over
  PEERS (another agent; see say.py): a hello with "token" (the shared
  peer secret) and "name" makes the connection a peer, answered with
  {"type": "peer_ok"}; a wrong token closes it, and so does a missing
  one from off this machine when web.require_token is on. A peer hello
  with "link": name is that machine's outbound link (config peer_link);
  one with "to": name is relayed down that link whole, every JSON frame
  each way wrapped as {"type": "relay", "rid": ..., "frame": {...}}
  ({"close": true} when either end goes). A peer's {"type": "deliver",
  "device": name, "frame": {"type": "grant", ...}} passes a device grant
  (grant.py) to that connected device, answered {"type": "delivered",
  "ok": b}.
  DEVICE ACTIONS (device.py, Pi Jarvis's tool): an app's hello carries
  "caps" {"role", "actions": [...]}, kept in devices.json. A peer's
  {"type": "device", "device": name, "frame": {"do": ...}} goes to that
  device as a phone frame with a numbered "id"; its phone_result echoes
  the id and comes back to the peer as {"type": "device_result", "ok",
  "text"} instead of starting a turn (no answer in DEVICE_WAIT_S: ok
  false). {"type": "devices"} answers {"type": "devices", "connected":
  [names]}. {"type": "caps", "caps"} from a device updates its entry
  (its role changed). A device whose devices.json entry has "role" is sent
  {"type": "role", "role"} on hello; the app gates every action by it
  (raising it needs a tap on the device).
  text frame  {"type": "listen", "on": b,   server -> browser: hands-
               "muted": b}
                                             free on or off for that
                                             tab. While on, the tab
                                             streams its mic (echo
                                             cancellation ON)
                                             continuously; frames
                                             outside a press feed
                                             ListenStream, and the voice
                                             line does the endpointing.
  text frame  {"type": "stt", "on": b}      client -> server: the phone's
                                             own recognizer is (or isn't)
                                             hearing its hands-free stream
  text frame  {"type": "heard", "text": ...}  client -> server: one
                                             hands-free utterance as the
                                             phone transcribed it (its
                                             recognizer endpoints); the
                                             server's own transcript of the
                                             same speech is then dropped,
                                             and used only when the phone
                                             had nothing

Every binary frame carries its own sample rate rather than assuming
16000, because a browser's actual capture rate is a cross-browser
coin flip (see ears.RATE and the resampling in record_until_release).

ONE reader loop per connection (Conn.reader): a WebSocket's incoming
message stream can only have a single consumer, so control frames
(press/release) and binary audio frames are both dispatched from that
one loop, never iterate `conn.ws` a second time anywhere else.
"""
import asyncio
import audioop
import base64
import collections
import hashlib
import hmac
import ipaddress
import json
import os
import queue
import struct
import time

import numpy as np
import websockets

from backtalk.vlog import log

RATE = 16000   # must match ears.RATE, the fixed transcribe() contract
# A tap's endpoint asks the client to release; past this the server ends
# it itself (a phone waits up to 3.5 s for its own transcript first).
ENDPOINT_WAIT_S = 6.0
# A press whose frames stop this long (a client that died mid-press) ends.
NO_AUDIO_S = 8.0
# Device ids of agent channels, not a person's device (see BrowserBridge.used)
AGENT_IDS = ("terminal-", "claude-")
CALL_VOICE_RMS = 500   # a caller frame this loud opens the call at the far end
CALL_RING_S = 20       # the caller has this long to start talking
DEVICE_WAIT_S = 120    # a device action's answer (a confirm card waits 90 s for a tap)
# A <<show>> picture rides in a "show" frame as a markdown data URL. Under
# this it goes as it is; over it, ffmpeg shrinks it to a JPEG at most
# IMAGE_SIDE px on its long side. The frame stays under IMAGE_MAX so no
# client's message limit (1 MB in many) can drop the socket.
IMAGE_KEEP = 400_000
IMAGE_SIDE = 1280
IMAGE_MAX = 900_000
IMAGE_TYPES = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp", ".gif": "gif"}
# Any other file that isn't text goes as a file card (name and size); a
# long press on it fetches it ("file_get") in FILE_CHUNK pieces, as an app
# update does, so a big file never rides in one frame.
FILE_MAX = 25 * 2**20
FILE_CHUNK = 256 * 1024
# devices with no screen for a picture (the hello's "model"): never sent one
NO_IMAGE_MODELS = ("Desk", "Galaxy Watch")


def image_card(path: str) -> str:
    """A picture file as one markdown line, ![name](data:image/...;base64,...),
    which the face draws as an image at card width (tap: full size)."""
    import subprocess
    kind = IMAGE_TYPES[os.path.splitext(path)[1].lower()]
    with open(path, "rb") as f:
        data = f.read(IMAGE_KEEP + 1)
    if len(data) > IMAGE_KEEP:
        for side, q in ((IMAGE_SIDE, 5), (960, 9)):     # q: ffmpeg's JPEG scale, 5 is about 80
            data = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", path, "-frames:v", "1", "-vf",
                 f"scale='min({side},iw)':'min({side},ih)':force_original_aspect_ratio=decrease",
                 "-q:v", str(q), "-f", "image2pipe", "-c:v", "mjpeg", "-"],
                capture_output=True, timeout=30, check=True).stdout
            kind = "jpeg"
            if len(data) * 4 // 3 < IMAGE_MAX:
                break
    b64 = base64.b64encode(data).decode()
    if len(b64) > IMAGE_MAX:
        raise ValueError(f"picture still {len(b64) // 1024} KB after shrinking")
    return f"![{os.path.basename(path).translate({91: None, 93: None})}](data:image/{kind};base64,{b64})"


def is_text(path: str) -> bool:
    """Shown as a document card (UTF-8, no NULs in its first 8 KB)?"""
    with open(path, "rb") as f:
        head = f.read(8192)
    if b"\0" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as e:
        return e.start > len(head) - 4    # only a character cut at the edge


def file_card(path: str) -> str:
    """A non-text file as one markdown line the face draws as a file card:
    [file: name](jarvis-file:<quoted path>#<size>)."""
    from urllib.parse import quote
    size = os.path.getsize(path)
    if size > FILE_MAX:
        raise ValueError(f"{size // 2**20} MB is over the {FILE_MAX // 2**20} MB file limit")
    return f"[file: {os.path.basename(path).translate({91: None, 93: None})}](jarvis-file:{quote(path)}#{size})"


def file_frames(path: str):
    """The file as {"type": "file_chunk", "path", "data", "last"} frames."""
    with open(path, "rb") as f:
        data = f.read(FILE_MAX + 1)
    if len(data) > FILE_MAX:
        raise ValueError("over the file limit")
    for i in range(0, max(len(data), 1), FILE_CHUNK):
        yield {"type": "file_chunk", "path": path, "last": i + FILE_CHUNK >= len(data),
               "data": base64.b64encode(data[i:i + FILE_CHUNK]).decode()}


def chime(rate: int) -> np.ndarray:
    """Two soft rising tones and a beat of silence: an announcement or a
    call is coming."""
    t = np.arange(int(rate * 0.14)) / rate
    env = np.sin(np.pi * t / t[-1])
    c = np.concatenate([np.sin(2 * np.pi * f * t) * env for f in (880, 1320)]
                       + [np.zeros(int(rate * 0.2))])
    return (c * 9000).astype(np.int16)


def beep(rate: int) -> np.ndarray:
    """One short soft tone: a tapped push to talk is listening."""
    t = np.arange(int(rate * 0.12)) / rate
    return (np.sin(2 * np.pi * 660 * t) * np.sin(np.pi * t / t[-1]) * 7000).astype(np.int16)


class Call:
    """An intercom call. The caller speaks first: their frames are held
    until one is loud enough, then the far end gets a chime, the call
    frame (its mic opens), and the held audio, and after that every frame
    goes straight across both ways."""

    def __init__(self, caller: "Conn", callee: "Conn"):
        self.caller, self.callee = caller, callee
        self.open = False
        self.held: collections.deque = collections.deque(maxlen=12)

    def peer(self, conn: "Conn") -> "Conn":
        return self.callee if conn is self.caller else self.caller


class Conn:
    """One browser tab's live connection."""

    def __init__(self, ws, bridge: "BrowserBridge"):
        self.ws = ws
        self.bridge = bridge
        # Set from the client's own "hello" (a random token the browser
        # generates once and keeps in sessionStorage, see core.js's
        # DEVICE_ID), not assigned here. A server-assigned counter
        # resets on every reconnect, silently reassigning the tab
        # mid-session; the client's token survives reloads and drops.
        self.id = None
        self.peer = None      # a peer agent's name, once its hello's token checks out
        self.via = None       # relayed whole down this peer link (a hello's "to")
        self.rid = None       # ...under this relay id
        self.peer_link = None # the name this peer's outbound link serves (a hello's "link")
        self.authed = True    # False: refused unless the first frame is a peer hello
        self.loopback = False # connected from this machine
        self.face = False     # this machine's own face (a loopback hello with no "model")
        self.disconnected = False
        self.recording = False   # this tab's own slot, not bridge-wide
        self.latched = False     # this press is a tap: it ends on silence (latch)
        self.tap_dropped = False # ...and nobody spoke into it
        self.listening = False   # hands-free: frames outside a press
        self.listen_muted = False   # paused: hearing only "start listening"
        self.call: Call | None = None   # an intercom call: audio relays, untranscribed
        # Agent speech for this device while it's on a call, at RATE, waiting
        # to be mixed into the far end's audio (Bridge._mix); see make_sink.
        self.overlay: "collections.deque[np.ndarray]" = collections.deque()
        self.relayed_at = 0.0   # when call audio last went to this device
        # Read from a worker thread (ListenStream), hence queue.Queue.
        # Bounded: a stalled listener drops audio, never memory.
        self._listen_q: "queue.Queue[tuple[float, bytes]]" = queue.Queue(maxsize=500)
        self.phone_stt = False   # the phone's recognizer hears the hands-free stream
        self.heard_at = 0.0      # when its last words ("heard") arrived
        # The last few seconds of hands-free audio as it arrived, (time,
        # frame): the voiceprint for the phone's words.
        self.recent: "collections.deque[tuple[float, bytes]]" = collections.deque(maxlen=100)
        self._frames: "asyncio.Queue" = asyncio.Queue()
        self._released = asyncio.Event()

    def heard_pcm(self, s: float = 6.0):
        """The audio before the phone's last words, for their voiceprint.
        a fixed window (the phone gives no timings), so it can
        hold silence or the end of earlier speech; fine for spotting a voice."""
        pcm = [f[4:] for t, f in list(self.recent)
               if self.heard_at - s <= t <= self.heard_at
               and len(f) > 4 and struct.unpack_from("<I", f, 0)[0] == 16000]
        return np.frombuffer(b"".join(pcm), dtype=np.int16) if pcm else None

    async def reader(self):
        """The only loop that ever reads this connection's socket."""
        try:
            async for msg in self.ws:
                if isinstance(msg, (bytes, bytearray)) and not self.authed:
                    log(f"[web] refused {self.ws.remote_address[0]}: audio before hello")
                    await self.ws.close(4401, "token required")
                    return
                if isinstance(msg, (bytes, bytearray)):
                    # A held press wins over a call (talking to the agent
                    # on a device a session owns; muted to the far end).
                    if self.call is not None and not self.recording:
                        self.bridge._call_audio(self, bytes(msg))
                    elif self.recording:
                        await self._frames.put(bytes(msg))
                    elif self.listening:
                        item = (time.monotonic(), bytes(msg))
                        if self.phone_stt:
                            self.recent.append(item)
                        try:
                            self._listen_q.put_nowait(item)
                        except queue.Full:
                            pass
                    continue
                try:
                    data = json.loads(msg)
                except ValueError:
                    continue
                kind = data.get("type")
                if not self.authed and not (kind == "hello" and (data.get("token")
                                                                or data.get("device_token"))):
                    log(f"[peer] refused {self.ws.remote_address[0]}: no token")
                    await self.ws.close(4401, "token required")
                    return
                if self.via:
                    self.bridge.relay_up(self, data)
                    continue
                if kind == "relay" and self.bridge.links.get(self.peer_link) is self:
                    self.bridge.relay_down(data)
                    continue
                if kind == "hello" and data.get("token") is None \
                        and data.get("device_token") is not None and not self.authed:
                    who = self.bridge.check_device_token(data["device_token"])
                    if who is None:
                        gone = self.bridge.device_token_revoked(data["device_token"])
                        log(f"[web] refused {self.ws.remote_address[0]}: "
                            + ("revoked device token" if gone else "wrong device token"))
                        await self.ws.close(*((4403, "revoked") if gone else (4401, "wrong token")))
                        return
                    self.authed = True
                    log(f"[web] device token for {who} accepted")
                if kind == "hello" and data.get("token") is not None:
                    if not self.bridge.check_token(data.get("token")):
                        log(f"[peer] refused {self.ws.remote_address[0]}: wrong token")
                        await self.ws.close(4401, "wrong token")
                        return
                    self.authed = True
                    self.peer = str(data.get("name") or "peer")[:40]
                    if data.get("to"):
                        if not self.bridge.relay_open(self, str(data["to"]), data):
                            await self.ws.close(4404, "no link")
                            return
                        continue
                    if data.get("link"):
                        self.peer_link = str(data["link"])
                        self.bridge.link_up(self)
                    log(f"[peer] {self.peer} connected"
                        + (f" (link for {self.peer_link})" if self.peer_link else ""))
                    await self.ws.send(json.dumps({"type": "peer_ok"}))
                    if self.peer_link:
                        continue
                if kind == "hello":
                    self.id = data.get("device_id") or self.id
                    self.face = self.loopback and not self.peer and not data.get("model")
                    self.bridge.saw(self, self.peer or data.get("model"), data.get("caps"))
                    role = self.bridge.devices().get(self.id, {}).get("role")
                    if role and not self.peer:
                        await self.ws.send(json.dumps({"type": "role", "role": role}))
                    self.bridge.offer_update(self, data.get("version"))
                    if self.bridge._lines.get(self.id):
                        await self.ws.send(json.dumps(
                            {"type": "lines", "lines": list(self.bridge._lines[self.id])}))
                    # Hands-free survives a reconnect; anything else is told
                    # it's off, or a client still in hands-free from before a
                    # restart streams to a server that drops it all.
                    if self.id in self.bridge._hf_ids:
                        self.bridge.set_listening(self, True, muted=self.bridge._hf_ids[self.id])
                    else:
                        await self.ws.send(json.dumps({"type": "listen", "on": False, "muted": False}))
                    if not self.peer:
                        await self.bridge.greet(self, data)
                elif kind == "text" and self.bridge.on_text is not None:
                    t = str(data.get("text") or "").strip()[:4000]
                    if t:
                        # "spoken": the phone transcribed it itself (on-device
                        # push to talk), so it's speech, not typing
                        self.bridge.on_text(self, t, bool(data.get("spoken")))
                    if self.id in self.bridge._hf_ids:
                        self.bridge.set_listening(self, True)
                elif kind == "stt":
                    self.phone_stt = bool(data.get("on"))
                    log(f"[web] phone recognizer {'on' if self.phone_stt else 'off'}"
                        f" for {str(self.id)[:8]}")
                elif kind == "heard" and self.bridge.on_heard is not None:
                    t = str(data.get("text") or "").strip()[:4000]
                    if t:
                        self.heard_at = time.monotonic()
                        self.bridge.on_heard(self, t)
                elif kind == "deliver" and self.peer:
                    await self.ws.send(json.dumps(
                        {"type": "delivered", "ok": self.bridge.deliver(self, data)}))
                elif kind == "caps" and self.id:
                    self.bridge.saw(self, None, data.get("caps"))   # its role changed
                elif kind == "device" and self.peer:
                    asyncio.ensure_future(self.bridge.device_call(self, data))
                elif kind == "devices" and self.peer:
                    await self.ws.send(json.dumps({"type": "devices", "connected": sorted(
                        {self.bridge.name_of(c.id) or str(c.id) for c in list(self.bridge._conns)
                         if c.id and not c.peer and not c.disconnected})}))
                elif kind == "reopen" and self.bridge.on_reopen is not None:
                    self.bridge.on_reopen(self, str(data.get("path") or ""))
                elif kind == "app_status":
                    # Android's installer on a self-update (0 installed, -1
                    # waiting for the person, 3 cancelled, others failed)
                    log(f"[app] {self.bridge.name_of(self.id)} install status "
                        f"{data.get('code')} {str(data.get('message') or '')[:200]}")
                elif kind == "file_get" and self.bridge.on_file_get is not None:
                    asyncio.ensure_future(self.bridge.on_file_get(self, str(data.get("path") or "")))
                elif kind == "app_get":
                    asyncio.ensure_future(self.bridge.send_update(self))
                elif kind == "hangup" and self.call:
                    self.bridge.end_call(self.call, "hung up")
                elif kind in ("press", "interrupt_press") and self.call \
                        and self.id not in self.bridge.owned:
                    # no session owns this device: a tap on the orb hangs up
                    self.bridge.end_call(self.call, "hung up")
                elif kind in ("interrupt", "abort") and self.bridge.on_control is not None:
                    self.bridge.on_control(self, kind)
                elif kind == "press":
                    self.bridge._on_press(self, interrupt=False)
                elif kind == "interrupt_press":
                    self.bridge._on_press(self, interrupt=True)
                elif kind == "latch" and self.recording:
                    # the press was a tap: end it on silence like hands-free
                    self.latched = True
                elif kind == "release":
                    # the phone's own transcript of this press, if it made
                    # one (on-device recognition fed the same audio)
                    self.release_text = str(data.get("text") or "").strip() or None
                    self._released.set()
                elif kind == "unmute" and self.listen_muted:
                    self.bridge.set_listening(self, True)
                elif kind == "hands_free":
                    # a silent switch from the client's own controls (the
                    # app's taps, its assistant gesture): no spoken line;
                    # on + muted = paused
                    self.bridge.set_listening(self, bool(data.get("on")),
                                              muted=bool(data.get("muted")))
                elif kind == "phone_result" and data.get("id") is not None:
                    fut = self.bridge._waiting.pop(str(data["id"]), None)
                    if fut is not None and not fut.done():
                        fut.set_result(str(data.get("text") or "done"))
                elif kind == "phone_result" and self.bridge.on_phone_result is not None:
                    self.bridge.on_phone_result(self, str(data.get("text") or ""))
                elif kind == "image" and self.bridge.on_image is not None:
                    try:
                        self.bridge.on_image(self, base64.b64decode(data.get("data") or ""))
                        await self.ws.send(json.dumps({"type": "image_ok"}))
                    except Exception as e:
                        log(f"[web] shared image dropped: {e}")
                elif kind == "image_drop" and self.bridge.on_drop is not None:
                    self.bridge.on_drop(self)
                elif kind == "file" and self.bridge.on_file is not None:
                    try:
                        name = str(data.get("name") or "file")
                        self.bridge.on_file(self, name, str(data.get("mime") or ""),
                                            base64.b64decode(data.get("data") or ""))
                        await self.ws.send(json.dumps({"type": "file_ok", "name": name}))
                    except Exception as e:
                        log(f"[web] shared file dropped: {e}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.disconnected = True
            self.bridge.peer_gone(self)
            if self.call is not None:
                self.bridge.end_call(self.call, "disconnected")
            self._released.set()         # unblock a capture awaiting release
            await self._frames.put(None)  # unblock a capture awaiting a frame


class BrowserBridge:
    """websockets.serve() wrapper. Every connected tab gets its own
    capture slot (Conn.recording), so N tabs can each record
    independently: the guard in _on_press is per-connection, not
    bridge-wide. _conns tracks every live connection so a sink can
    broadcast to all of them (see make_broadcast_sink)."""

    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._server = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._press_q: "asyncio.Queue[tuple[Conn, bool]]" = asyncio.Queue()
        self._conns: set[Conn] = set()
        # Devices in hands-free, by the browser's own token, so a reload
        # or reconnect comes back listening. Memory only: a voice-line
        # restart returns every browser to push-to-talk.
        self._hf_ids: dict[str, bool] = {}     # ...and whether paused
        self.on_listen = None   # main.py: start a listener for a Conn
        self.on_image = None    # main.py: (Conn, jpeg bytes), a shared picture
        self.on_file = None     # main.py: (Conn, name, mime, bytes), any other shared file
        self.on_phone_result = None   # main.py: (Conn, text) from a phone command
        self.devices_file = None      # main.py: the device names (see saw)
        self.update_dir = None        # main.py: where a newer app waits (see offer_update)
        self.on_text = None           # main.py: (Conn, text) typed in the terminal
        self.on_heard = None          # main.py: (Conn, text) hands-free words from the phone
        self.on_reopen = None         # main.py: (Conn, path) a card's reopen button
        self.on_file_get = None       # main.py: async (Conn, path) a file card's save
        self.on_drop = None           # main.py: (Conn) the pictures and files it shared, discarded
        self.on_control = None        # main.py: (Conn, "interrupt" | "abort")
        # Devices a dedicated session owns (main.py's sessions, by id): the
        # main session's broadcasts skip them, so its replies and stops
        # never land on, say, the kitchen mid-recipe.
        self.owned: dict = {}
        # Per device id: until when its speaker is busy with something
        # that isn't an announcement (make_sink). Announcements wait for a
        # lull and pause when it gets busy again (main.py).
        self.voice_until: dict[str, float] = {}
        # Each device's recent conversation lines, replayed on hello so a
        # reload keeps its terminal. Memory only.
        self._lines: dict[str, collections.deque] = {}
        self._token = None            # the peer secret, read once (see check_token)
        self.links: dict[str, Conn] = {}    # peer links, by the name they serve
        self._relays: dict[str, Conn] = {}  # relayed connections, by rid
        self.tokens_file = None   # main.py: device token hashes (see grant.py)
        self.todo_file = None     # main.py: the session to-do list (see todo.py)
        self.todo_txt = None      # main.py: a plain-text list instead (config todo_txt)
        self.task_source = None   # main.py: () -> the brain's running tasks, [{"text"}]
        self.signals_dir = None   # main.py: the bus, for pushed state
        self.identity = {"type": "identity", "name": "", "color": "", "face": ""}
        self.on_switch = None     # main.py: (Conn) the person just picked this assistant
        self._cook: dict[str, dict] = {}    # device id -> its cooking steps frame
        self._tasks = None                  # the last tasks frame sent
        self._waiting: dict[str, asyncio.Future] = {}   # device actions by id (device_call)
        self._next_id = 0
        # The devices sir last spoke or typed on, newest first (None: this
        # machine's own key); see used() and pin().
        self._recent: list = []

    # ---- where a turn nobody asked for goes (a helper finishing, a task
    # notification): the device sir last used, never every device

    def used(self, sink):
        """sir just spoke or typed through this sink (None: this machine's
        own key or mic). Agent channels never count: peers, the laptop
        Claude's jarvis-ask, and the desktop terminal-chat (device ids
        starting AGENT_IDS)."""
        conn = getattr(sink, "conn", None)
        if conn is not None and (conn.peer or str(conn.id).startswith(AGENT_IDS)):
            return
        # one history for everyone; key it by person (devices.json
        # owner, the voiceprint) once ma'am's devices shouldn't take sir's reports
        key = conn.id if conn is not None else None
        self._recent = [conn] + [c for c in self._recent
                                 if (c.id if c is not None else None) != key][:7]

    def pin(self):
        """The sink a background turn speaks to, chosen once for the whole
        turn: the most recently used device still connected (not one a
        dedicated session owns); none connected, the last one (its lines
        wait for its reconnect, see make_sink); never used, None (this
        machine's own speakers)."""
        for c in self._recent:
            if c is None:
                return None
            live = next((x for x in list(self._conns) if x.id == c.id
                         and not x.disconnected and x.id not in self.owned), None)
            if live is not None:
                return self.make_sink(live)
        return self.make_sink(self._recent[0]) if self._recent else None

    def make_recent_sink(self):
        """brain.remote_sink, the fallback for a turn nobody asked for. The
        brain pins it per turn (pin); used unpinned, each call goes to
        pin()'s device. A stop still reaches every device, so an
        interrupt silences whatever is playing."""
        every = self.make_broadcast_sink()

        def _sink(rate: int, pcm: np.ndarray):
            s = self.pin()
            if s is not None:
                s(rate, pcm)

        def _call(name):
            def f(*a):
                s = self.pin()
                if s is not None:
                    getattr(s, name)(*a)
            return f
        _sink.reply_done = _call("reply_done")
        _sink.send = _call("send")
        _sink.stop = every.stop
        _sink.pin = self.pin
        return _sink

    # ---- device tokens (see grant.py): hashes only, read fresh each
    # time, so a revoke applies at the next connect

    def check_device_token(self, tok) -> str | None:
        """The device a token was issued to, or None."""
        try:
            with open(self.tokens_file) as f:
                entry = json.load(f).get(hashlib.sha256(str(tok).encode()).hexdigest())
        except (OSError, TypeError, ValueError):
            return None
        return str(entry.get("device") or "device") if isinstance(entry, dict) else None

    def device_token_revoked(self, tok) -> bool:
        """grant.py --revoke took this token back (its hash kept under "revoked")."""
        try:
            with open(self.tokens_file) as f:
                return hashlib.sha256(str(tok).encode()).hexdigest() in (json.load(f).get("revoked") or {})
        except (OSError, TypeError, ValueError, AttributeError):
            return False

    def deliver(self, peer: Conn, data: dict) -> bool:
        """A peer passes a grant to one of this bridge's devices (it is
        never kept or logged here)."""
        frame, conn = data.get("frame"), self.find(str(data.get("device") or ""))
        ok = conn is not None and isinstance(frame, dict) and frame.get("type") == "grant"
        if ok:
            self._send(conn, frame)
        log(f"[peer] {peer.peer}'s grant for {data.get('device')!r} "
            + ("delivered" if ok else "not delivered"))
        return ok

    async def device_call(self, peer: Conn, data: dict):
        """A peer's device action (device.py): to the named device as a
        numbered phone frame, its answer back to the peer."""
        name, frame = str(data.get("device") or ""), data.get("frame")
        conn = self.find(name)
        if not isinstance(frame, dict) or not frame.get("do"):
            ok, text = False, "the frame needs a \"do\""
        elif conn is None:
            ok, text = False, f"{name!r} isn't connected"
        elif not (self.devices().get(conn.id, {}).get("caps") or {}).get("actions"):
            ok, text = False, f"{name!r} runs an app too old for device actions (it lists none)"
        else:
            self._next_id += 1
            rid = str(self._next_id)
            fut = self._waiting[rid] = asyncio.get_running_loop().create_future()
            self._send(conn, {**frame, "type": "phone", "id": rid})
            log(f"[device] {peer.peer} -> {name}: {json.dumps(frame)[:200]}")
            try:
                ok, text = True, await asyncio.wait_for(fut, DEVICE_WAIT_S)
            except asyncio.TimeoutError:
                ok, text = False, f"no answer from {name!r} in {DEVICE_WAIT_S} s"
            finally:
                self._waiting.pop(rid, None)
        log(f"[device] {name}: {'ok' if ok else 'failed'}: {text[:200]}")
        try:
            await peer.ws.send(json.dumps({"type": "device_result", "ok": ok, "text": text}))
        except Exception:
            pass

    # ---- what a device sees besides the conversation: who this is, the
    # session's to-do list and running tasks, cooking steps, and (for a
    # device with no face server to poll) the face's state

    async def greet(self, conn: Conn, hello: dict):
        conn.push = bool(hello.get("push"))
        # "controls": this bridge takes interrupt and abort (the three controls);
        # a client without it falls back to interrupt_press
        await conn.ws.send(json.dumps(self.identity | {"controls": 1}))
        await conn.ws.send(json.dumps(self._tasks or self.tasks_frame()))
        if conn.id in self._cook:
            await conn.ws.send(json.dumps(self._cook[conn.id]))
        if hello.get("switched") and self.on_switch is not None:
            self.on_switch(conn)

    def tasks_frame(self) -> dict:
        """{"waiting", "running", "review", "todo", "done"}, each [{"text"}]:
        the to-do file's items by state, then the brain's background tasks
        as running."""
        out = {"type": "tasks", "waiting": [], "running": [], "review": [], "todo": [], "done": []}
        try:
            if self.todo_txt:
                pre = {">": "progress", "!": "review", "<": "done", "?": "waiting"}
                with open(self.todo_txt) as f:
                    items = [{"text": ln[1:].strip(), "state": pre[ln[0]]} if ln[0] in pre else {"text": ln}
                             for ln in map(str.strip, f) if ln and not ln.startswith("#")]
            else:
                with open(self.todo_file) as f:
                    items = json.load(f)
        except (OSError, TypeError, ValueError):
            items = []
        for it in items if isinstance(items, list) else []:
            kind = {"waiting": "waiting", "progress": "running", "review": "review",
                    "done": "done"}.get(it.get("state"), "todo")
            out[kind].append({"text": str(it.get("text", ""))[:200]})
        try:
            bg = self.task_source() if self.task_source else []
            out["running"] += bg
            out["background"] = len(bg)     # the face's task count: Interrupt shows while > 0
        except Exception:
            pass
        return out

    def set_cook(self, conn_id: str, steps: list, current: int = 0):
        """A cooking session's steps for its device ([] = cooking's over)."""
        frame = {"type": "cook", "steps": [str(x)[:200] for x in steps][:40], "current": int(current)}
        if frame["steps"]:
            self._cook[conn_id] = frame
        else:
            self._cook.pop(conn_id, None)
        for c in list(self._conns):
            if c.id == conn_id and not c.disconnected:
                self._send(c, frame)

    def bus_state(self, conn_id) -> dict:
        """The face's state, as the face server's /state has it (shared bus
        only, plus this device's timers).
        a device owned by a dedicated session shows the main
        session's state here; read .voice_devices' entry if one ever does."""
        def read(name, default=""):
            try:
                with open(os.path.join(self.signals_dir, name)) as f:
                    return f.read().strip()
            except (OSError, TypeError):
                return default
        state = read(".voice_state", "idle").lower()
        samples, level = [0.0] * 64, 0.0
        try:
            w = json.loads(read(".voice_waveform", "{}"))
            if w.get("samples") and time.time() - float(w.get("ts", 0)) < 0.6:
                state, samples = "speaking", [float(x) for x in w["samples"][:64]]
                level = min(1.0, sum(abs(x) for x in samples) / len(samples) / 3000.0)
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            timers = json.loads(read(".voice_devices", "{}")).get(conn_id, {}).get("timers") or []
        except (ValueError, AttributeError):
            timers = []
        tasks = read(".voice_tasks", "0")
        try:
            speed = json.loads(read(".voice_speed", "{}"))
        except ValueError:
            speed = {}
        return {"type": "state", "state": state, "level": level, "samples": samples, "speed": speed,
                "loading": os.path.exists(os.path.join(self.signals_dir or "", ".voice_loading_pid")),
                "tasks": int(tasks) if tasks.isdigit() else 0,
                "active_conn": read(".voice_active_conn"), "timers": timers}

    async def _push_watch(self):
        """Tasks to every device when they change (polled each second, so
        the to-do file needs no notifier), and the face's state to the
        devices that asked for it, about eight times a second."""
        n = 0
        while True:
            await asyncio.sleep(0.125)
            n += 1
            conns = [c for c in list(self._conns) if c.id and not c.peer and not c.disconnected]
            if n % 8 == 0:
                t = self.tasks_frame()
                if t != self._tasks:
                    self._tasks = t
                    for c in conns:
                        self._send(c, t)
            for c in conns:
                if getattr(c, "push", False) and self.signals_dir:
                    st = self.bus_state(c.id)
                    if st != getattr(c, "last_state", None):
                        c.last_state = st
                        self._send(c, st)

    # ---- peers (see the docstring's PEERS)

    def check_token(self, tok) -> bool:
        if self._token is None:
            from backtalk.config import peer_token
            self._token = peer_token()
        return bool(self._token) and hmac.compare_digest(str(tok), self._token)

    def link_up(self, conn: Conn):
        old = self.links.get(conn.peer_link)
        self.links[conn.peer_link] = conn
        if old is not None and old is not conn:
            asyncio.ensure_future(old.ws.close())   # a stale link from before a sleep

    def relay_open(self, conn: Conn, to: str, hello: dict) -> bool:
        if to not in self.links:
            log(f"[peer] {conn.peer} asked for {to}, which has no link up")
            return False
        conn.via, conn.rid = to, f"{id(conn):x}"
        self._relays[conn.rid] = conn
        log(f"[peer] {conn.peer} relayed to {to}")
        self.relay_up(conn, {k: v for k, v in hello.items() if k != "to"})
        return True

    def relay_up(self, conn: Conn, frame: dict | None):
        link = self.links.get(conn.via)
        if link is None:
            asyncio.ensure_future(conn.ws.close(4404, "link gone"))
            return
        self._send(link, {"type": "relay", "rid": conn.rid}
                   | ({"frame": frame} if frame is not None else {"close": True}))

    def relay_down(self, data: dict):
        conn = self._relays.get(str(data.get("rid")))
        if conn is None:
            return
        if data.get("close"):
            asyncio.ensure_future(conn.ws.close())
        elif isinstance(data.get("frame"), dict):
            self._send(conn, data["frame"])

    def peer_gone(self, conn: Conn):
        if conn.via and self._relays.pop(conn.rid, None):
            self.relay_up(conn, None)
        if conn.peer_link and self.links.get(conn.peer_link) is conn:
            del self.links[conn.peer_link]
            log(f"[peer] link for {conn.peer_link} down")
            for c in [c for c in self._relays.values() if c.via == conn.peer_link]:
                asyncio.ensure_future(c.ws.close(4404, "link gone"))

    async def serve(self):
        self._loop = asyncio.get_running_loop()
        host = self._cfg.get("host", "127.0.0.1")
        port = self._cfg.get("port", 8792)

        async def handler(ws):
            conn = Conn(ws, self)
            # off this machine, with require_token on: a peer, or nothing
            addr = ipaddress.ip_address(ws.remote_address[0])
            local = addr.is_loopback or bool(getattr(addr, "ipv4_mapped", None)
                                             and addr.ipv4_mapped.is_loopback)
            conn.authed = local or not self._cfg.get("require_token")
            conn.loopback = local
            self._conns.add(conn)
            try:
                await conn.reader()   # runs until this connection closes
            finally:
                self._conns.discard(conn)

        self._server = await websockets.serve(handler, host, port,
                                              max_size=48 * 2**20)   # shared pictures and files (~35 MB after base64)
        log(f"[web] browser bridge listening on ws://{host}:{port}")
        asyncio.ensure_future(self._update_watch())
        asyncio.ensure_future(self._push_watch())
        await self._server.wait_closed()

    def _on_press(self, conn: Conn, interrupt: bool = False):
        """Called synchronously from within conn.reader(), already on
        the event loop, no thread hop needed here. `interrupt` is the
        Interrupt button (stop the current turn, then record) versus a
        plain tap (queue behind it, touch nothing). This guard is about
        overlapping RECORDINGS on ONE connection, not overlapping
        turns or other tabs; a press queues fine the instant THIS
        tab's previous recording ends, and a different tab's press is
        never affected by it at all."""
        if conn.recording:
            log("[web] press ignored, this tab is already recording")
            # ...and ended at the client, which would otherwise hold it
            # (its reply paused) until the next tap
            self._send(conn, {"type": "endpoint", "speech": False})
            return
        conn.recording = True
        conn.latched = conn.tap_dropped = False
        conn.release_text = None
        conn._released.clear()
        while not conn._frames.empty():
            conn._frames.get_nowait()   # drop anything stale from before this press
        self._press_q.put_nowait((conn, interrupt))

    def set_listening(self, conn: Conn, on: bool, muted: bool = False):
        """Hands-free on or off for one tab. Call on the event loop.
        on + muted is paused ("stop listening"): the tab keeps
        streaming, but main.py acts on nothing except "start
        listening", and a click on the face also resumes."""
        conn.listening, conn.listen_muted = on, muted and on
        conn.active = time.monotonic()      # the hands-free idle clock
        if conn.id:
            if on:
                self._hf_ids[conn.id] = conn.listen_muted
            else:
                self._hf_ids.pop(conn.id, None)
        if not on:
            while not conn._listen_q.empty():
                conn._listen_q.get_nowait()
        asyncio.ensure_future(
            conn.ws.send(json.dumps({"type": "listen", "on": on,
                                     "muted": conn.listen_muted})))
        log(f"[web] hands-free {'off' if not on else 'paused' if muted else 'on'}"
            f" for {str(conn.id)[:8]}")
        if on and self.on_listen is not None:
            self.on_listen(conn)

    # ---- device names: "the kitchen" is a wall display. A JSON file of
    # {device_id: {"name", "model", "seen"}}; a new device is named after
    # its model (or "browser xxxx"), and the agent renames one by editing
    # the file. Read fresh each time, so its edits apply at once.

    def devices(self) -> dict:
        try:
            with open(self.devices_file) as f:
                return json.load(f)
        except (OSError, TypeError, ValueError):
            return {}

    def saw(self, conn: Conn, model: str | None, caps=None):
        if not (self.devices_file and conn.id):
            return
        devs = self.devices()
        d = devs.setdefault(conn.id, {"name": model or f"browser {conn.id[:4]}"})
        if isinstance(caps, dict):
            d["caps"] = caps    # what the app can do there (device.py)
        if model:
            d["model"] = model
            if d.get("name") == f"browser {conn.id[:4]}":
                d["name"] = model     # first seen on an app too old to say
        d["seen"] = time.strftime("%Y-%m-%d %H:%M")
        tmp = self.devices_file + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(devs, f, indent=1)
            os.replace(tmp, self.devices_file)
        except OSError as e:
            log(f"[web] device list not saved: {e}")

    # ---- app updates: the newest Android app waits in update_dir as
    # app.apk plus version.json {"code": N}. A client whose hello says an
    # older "version" is offered it; on "app_get" it's sent down the same
    # socket in base64 chunks ({"type": "app_chunk", "data", "last"}) and
    # the app installs it. No adb, no cable, no store.

    def _latest(self) -> int:
        try:
            with open(os.path.join(self.update_dir, "version.json")) as f:
                return int(json.load(f)["code"])
        except (OSError, TypeError, ValueError, KeyError):
            return 0

    def offer_update(self, conn: Conn, version):
        """Offer the newer build, once per build per connection (declining
        isn't nagged; a reconnect asks again)."""
        if version is not None:
            conn.version = int(version)
        if not self.update_dir or getattr(conn, "version", None) is None:
            return
        latest = self._latest()
        if latest > conn.version and getattr(conn, "offered", 0) < latest:
            conn.offered = latest
            self._send(conn, {"type": "app_update", "code": latest})
            log(f"[app] {self.name_of(conn.id)} has version {conn.version}, offered {latest}")

    async def _update_watch(self):
        """A device that stays connected for days (the kitchen) hears about
        a newly parked build too, within ten minutes."""
        while True:
            await asyncio.sleep(600)
            for c in list(self._conns):
                if not c.disconnected:
                    self.offer_update(c, None)

    async def send_update(self, conn: Conn, chunk: int = 256 * 1024):
        try:
            with open(os.path.join(self.update_dir, "app.apk"), "rb") as f:
                apk = f.read()
        except (OSError, TypeError) as e:
            log(f"[app] no update to send: {e}")
            return
        for i in range(0, len(apk), chunk):
            last = i + chunk >= len(apk)
            await conn.ws.send(json.dumps({"type": "app_chunk", "last": last,
                                           "data": base64.b64encode(apk[i:i + chunk]).decode()}))
        log(f"[app] sent {len(apk) // 1024} KB to {self.name_of(conn.id)}")

    def name_of(self, conn_id) -> str | None:
        return self.devices().get(conn_id, {}).get("name") if conn_id else None

    def find(self, name: str) -> Conn | None:
        """The live connection of the device with this name (any case)."""
        ids = {i for i, d in self.devices().items()
               if str(d.get("name", "")).casefold() == name.strip().casefold()}
        return next((c for c in list(self._conns)
                     if c.id in ids and not c.disconnected), None)

    # ---- intercom (see Call). start_call and end_call run on the loop.

    def start_call(self, caller: Conn, callee: Conn):
        if caller is callee:
            raise ValueError("that's the device asking")
        busy = [c for c in (caller, callee) if c.call is not None]
        if busy:
            raise RuntimeError(f"{self.name_of(busy[0].id)} is already on a call")
        call = Call(caller, callee)
        caller.call = callee.call = call
        self._send(caller, {"type": "call", "on": True, "with": self.name_of(callee.id)})
        self._loop.call_later(CALL_RING_S, lambda: call.open or self.end_call(call, "nobody spoke"))
        log(f"[call] {self.name_of(caller.id)} -> {self.name_of(callee.id)}: waiting for the caller to speak")

    def end_call(self, call: Call, why: str):
        if call.caller.call is not call:
            return                          # already over
        for c in (call.caller, call.callee):
            c.call = None
            if c is call.caller or call.open:
                self._send(c, {"type": "call", "on": False})
        log(f"[call] {self.name_of(call.caller.id)} -> {self.name_of(call.callee.id)} ended: {why}")

    def _call_audio(self, conn: Conn, frame: bytes):
        call = conn.call
        if call.open:
            peer = call.peer(conn)
            peer.relayed_at = time.monotonic()
            self._send(peer, self._mix(peer, frame))
            return
        if conn is not call.caller or len(frame) < 6:
            return                          # the far end isn't on yet
        call.held.append(frame)
        pcm = np.frombuffer(frame[4:len(frame) - (len(frame) - 4) % 2], dtype=np.int16)
        if np.sqrt(np.mean(pcm.astype(np.float32) ** 2)) < CALL_VOICE_RMS:
            return
        call.open = True
        rate = struct.unpack_from("<I", frame, 0)[0]
        self._send(call.callee, struct.pack("<I", rate) + chime(rate).tobytes())
        self._send(call.callee, {"type": "call", "on": True, "with": self.name_of(conn.id)})
        call.callee.relayed_at = time.monotonic()
        while call.held:
            self._send(call.callee, call.held.popleft())
        log(f"[call] {self.name_of(conn.id)} -> {self.name_of(call.callee.id)}: connected")

    # ---- the agent talking over a call: its speech for a device on a
    # call is queued (Conn.overlay) and mixed into the far end's frames,
    # the call ducked under it, so a cooking step plays without dropping
    # the call. When the far end sends nothing (a browser taking turns),
    # _drain plays the speech on its own.

    def _overlay_take(self, conn: Conn, n: int) -> np.ndarray:
        out, got = [], 0
        while conn.overlay and got < n:
            a = conn.overlay.popleft()
            if got + len(a) > n:
                conn.overlay.appendleft(a[n - got:])
                a = a[:n - got]
            out.append(a)
            got += len(a)
        return np.concatenate(out) if out else np.zeros(0, np.int16)

    def _mix(self, conn: Conn, frame: bytes) -> bytes:
        if not conn.overlay or len(frame) < 6:
            return frame
        rate = struct.unpack_from("<I", frame, 0)[0] or RATE
        call = np.frombuffer(frame[4:len(frame) - (len(frame) - 4) % 2], dtype=np.int16)
        take = self._overlay_take(conn, max(1, round(len(call) * RATE / rate)))
        if len(take) != len(call):      # to the call's rate and length
            take = np.interp(np.linspace(0, len(take) - 1, len(call)),
                             np.arange(len(take)), take)
        mixed = np.clip(call * 0.35 + take, -32768, 32767).astype(np.int16)
        return struct.pack("<I", rate) + mixed.tobytes()

    def overlay_add(self, conn: Conn, rate: int, pcm: np.ndarray):
        """Speech for a device on a call (from any thread)."""
        if rate != RATE:
            pcm = np.interp(np.linspace(0, len(pcm) - 1, round(len(pcm) * RATE / rate)),
                            np.arange(len(pcm)), pcm).astype(np.int16)
        conn.overlay.append(pcm)
        if not getattr(conn, "draining", False):
            conn.draining = True
            asyncio.run_coroutine_threadsafe(self._drain(conn), self._loop)

    async def _drain(self, conn: Conn):
        block = RATE // 10
        try:
            while conn.overlay and not conn.disconnected:
                if time.monotonic() - conn.relayed_at > 0.25:
                    pcm = self._overlay_take(conn, block)
                    await conn.ws.send(struct.pack("<I", RATE) + pcm.tobytes())
                await asyncio.sleep(0.1)
        except Exception:
            conn.overlay.clear()
        finally:
            conn.draining = False

    def _send(self, conn: Conn, obj):
        """One frame (bytes) or message (dict) to a connection, from the loop."""
        data = obj if isinstance(obj, bytes) else json.dumps(obj)

        async def send():
            try:
                await conn.ws.send(data)
            except Exception:
                pass                        # gone; its reader ends the call
        asyncio.ensure_future(send())

    async def stop(self):
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def wait_press(self) -> tuple[Conn, bool]:
        return await self._press_q.get()

    async def record_until_release(self, conn: Conn, abort=None,
                                   on_audio=None, max_s=120.0) -> np.ndarray | None:
        """Collect PCM frames until release, disconnect, or abort().
        `on_audio`, if given, also gets each 16 kHz chunk as it arrives
        (a streaming transcriber; see ears.Session).
        Resamples any frame whose declared rate isn't already 16000
        (defense against browser/engine quirks) via stdlib audioop,
        no new dependency. Returns None on no audio at all.
        A tapped press (latch) is endpointed here: on silence after
        speech, or no speech at all, the client is told {"type":
        "endpoint", "speech": b} and sends its release as for a second
        tap (so a phone's own transcript still rides along); no speech
        sets conn.tap_dropped and returns None. A press with no audio
        for NO_AUDIO_S, or open for max_s, is ended as nothing heard."""
        from backtalk.ears import Endpoint
        frames: list[np.ndarray] = []
        ep, told = None, 0.0
        # audioop.ratecv's filter memory, carried across chunks. Passing
        # None on every chunk instead of this would reset the resample
        # filter at each chunk boundary, glitching audio once per chunk
        # whenever the browser's actual mic rate isn't exactly 16000
        # (common: many browsers ignore the AudioContext sampleRate
        # request).
        resample_state = None
        start = last = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                if now - last > NO_AUDIO_S or now - start > max_s:
                    log(f"[web] press {'got no audio' if now - last > NO_AUDIO_S else 'hit the cap'}"
                        f" after {now - start:.0f}s, ending it as nothing heard")
                    self._send(conn, {"type": "endpoint", "speech": False})
                    return None
                if abort and abort():
                    # cut here (a mode switch): the client's press ends too
                    self._send(conn, {"type": "endpoint", "speech": False})
                    return None
                if conn._released.is_set() and conn._frames.empty():
                    break
                if told and time.monotonic() - told > ENDPOINT_WAIT_S:
                    log("[web] no release after the tap's endpoint, ending it here")
                    break
                try:
                    chunk = await asyncio.wait_for(conn._frames.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                if chunk is None:   # disconnect sentinel
                    break
                last = time.monotonic()
                if len(chunk) < 4:
                    continue
                rate = struct.unpack_from("<I", chunk, 0)[0]
                pcm_bytes = chunk[4:]
                if rate != RATE and rate > 0:
                    pcm_bytes, resample_state = audioop.ratecv(
                        pcm_bytes, 2, 1, rate, RATE, resample_state)
                frames.append(np.frombuffer(pcm_bytes, dtype=np.int16))
                if on_audio is not None:
                    on_audio(frames[-1])
                if conn.latched and not told:
                    ep = ep or Endpoint()
                    end = ep.feed(frames[-1])
                    if end:
                        told = time.monotonic()
                        conn.tap_dropped = end == "none"
                        log(f"[web] tap {'ended on silence' if end == 'end' else 'with no speech, dropping'}"
                            f" after {sum(map(len, frames)) / RATE:.1f}s")
                        self._send(conn, {"type": "endpoint", "speech": end == "end"})
        finally:
            conn.recording = False
        if not frames or conn.tap_dropped:
            return None
        return np.concatenate(frames)

    def make_sink(self, conn: Conn, low: bool = False, mirror: bool = True):
        """Returns a (rate, pcm) -> None closure for mouth.py's _write
        to call per audio block. `low`: an announcement's audio, which
        yields to everything else; any other audio marks the device as
        busy talking (voice_until) so announcements wait for a lull. Must never let a dead browser socket
        affect local playback, every failure is swallowed here, not
        left for the caller to handle. `mirror`: its "line" frames also
        go to this machine's face (see _send)."""
        loop = self._loop

        def live():
            """The connection to send to NOW: this one, or, if its tab was
            reloaded, the new connection with the same device id, so a
            reply carries on mid-sentence instead of going to a dead one."""
            if not conn.disconnected:
                return conn
            for c in list(self._conns):
                if c.id is not None and c.id == conn.id and not c.disconnected:
                    return c
            return None

        def _sink(rate: int, pcm: np.ndarray):
            c = live()
            if c is None or loop is None:
                return
            if not low and conn.id:
                self.voice_until[conn.id] = time.monotonic() + len(pcm) / rate + 0.3
            if c.call is not None and c.call.open:
                self.overlay_add(c, rate, pcm)     # mixed into the call
                return
            try:
                frame = struct.pack("<I", rate) + pcm.tobytes()
                asyncio.run_coroutine_threadsafe(c.ws.send(frame), loop)
            except Exception:
                pass

        def _send(obj: dict):
            if obj.get("type") == "line" and conn.id:
                self._lines.setdefault(conn.id, collections.deque(maxlen=60)).append(obj)
                # a remote device's turn also shows, silently, in this
                # machine's face terminal (text only: audio and the
                # active device stay with the asker)
                if mirror and not (conn.face or conn.peer):
                    for f in [f for f in list(self._conns) if f.face and f.id != conn.id]:
                        self.make_sink(f).send(obj)
            c = live()
            if c is None or loop is None:
                return
            try:
                asyncio.run_coroutine_threadsafe(c.ws.send(json.dumps(obj)), loop)
            except Exception:
                pass

        def _reply_done():
            _send({"type": "reply_done"})

        def _stop():
            """An interrupt: tell the browser to discard every chunk
            already sent but not yet played, mirrors mouth.shut_up()
            on this end."""
            c = live()
            if c is not None and c.call is not None:
                c.overlay.clear()       # never "stop" a call's own audio
                return
            _send({"type": "stop"})

        _sink.reply_done = _reply_done
        _sink.stop = _stop
        _sink.send = _send
        _sink.conn_id = conn.id
        _sink.conn = conn
        # Live lookup, not a snapshot: a sink can sit queued in
        # brain.py's _ask_queue for a while before its turn starts,
        # and the tab it belongs to may have long since closed by
        # then; see is_live's use there.
        _sink.is_live = lambda: live() is not None
        return _sink

    def make_broadcast_sink(self):
        """A (rate, pcm) -> None closure for every device connected AT
        SEND TIME (built fresh from self._conns each call). Only an
        interrupt's stop uses it now: a turn nobody asked for goes to one
        device (make_recent_sink)."""
        def conns():
            return [c for c in list(self._conns) if c.id not in self.owned and c.peer is None]

        def _sink(rate: int, pcm: np.ndarray):
            for conn in conns():
                self.make_sink(conn)(rate, pcm)

        def _reply_done():
            for conn in conns():
                self.make_sink(conn).reply_done()

        def _stop():
            for conn in conns():
                self.make_sink(conn).stop()

        def _send(obj: dict):
            for conn in conns():
                self.make_sink(conn, mirror=False).send(obj)

        _sink.reply_done = _reply_done
        _sink.stop = _stop
        _sink.send = _send
        return _sink


class ListenStream:
    """One tab's hands-free audio as a mic-shaped stream for
    ears.Ears.listen_once(stream=...): read(n) blocks for n samples at
    RATE, resampling whatever rate the browser actually captures at.
    A gap in the audio (network stall) reads as silence after 100ms,
    so the caller's abort check keeps getting a turn. `t` is when the
    newest audio read so far arrived (the listener can run behind)."""

    def __init__(self, conn: Conn):
        self.conn = conn
        self._buf = np.zeros(0, dtype=np.int16)
        self._state = None
        self.t = time.monotonic()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n: int):
        while len(self._buf) < n:
            try:
                self.t, chunk = self.conn._listen_q.get(timeout=0.1)
            except queue.Empty:
                self.t = time.monotonic()
                # A gap: hand back what's here padded with silence. Waiting
                # for the rest froze the listener mid-utterance when the tab
                # stopped streaming (switched to push to talk), so its
                # capturing flag (the listening rings, the quiet-restart
                # check) never cleared, and abort was never checked.
                out = np.zeros(n, dtype=np.int16)
                out[:len(self._buf)] = self._buf
                self._buf = self._buf[:0]
                return out.reshape(-1, 1), False
            if len(chunk) < 4:
                continue
            rate = struct.unpack_from("<I", chunk, 0)[0]
            pcm = chunk[4:]
            if rate != RATE and rate > 0:
                pcm, self._state = audioop.ratecv(pcm, 2, 1, rate, RATE,
                                                  self._state)
            self._buf = np.concatenate(
                [self._buf, np.frombuffer(pcm, dtype=np.int16)])
        out, self._buf = self._buf[:n], self._buf[n:]
        return out.reshape(-1, 1), False
