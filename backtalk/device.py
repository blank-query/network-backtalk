# backtalk: talk to your Claude Code agent out loud.
# Copyright (C) 2026 blank-query
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
"""ACT ON A DEVICE, AS A TOOL: run one action on any connected device by
name and print what came of it, inside the same turn.

  python -m backtalk.device "<device name>" '{"do": "battery"}'
  python -m backtalk.device --list     connected devices, with each one's
                                       role and actions (from its hello)

The action goes down the device's own socket through this machine's
bridge (numbered, web.py's DEVICE ACTIONS, so the frame may not carry its
own "id"); the device answers when it's done. The device enforces its role
and confirmation rules itself: on sir's phone (role full) nothing needs a
tap, so the assistant reads back each send and acts only on his spoken yes;
elsewhere a read or a send asked this way shows a confirm card there and
waits up to 90 s for a tap. Exit 1 when the device isn't connected, its app
is too old, or no answer comes.
"""
import asyncio
import json
import os
import sys

import websockets


async def ask(url: str, token: str, me: str, frame: dict, wait: float = 130) -> dict:
    from backtalk.say import MAX, hello
    async with websockets.connect(url, max_size=MAX, open_timeout=10) as ws:
        await ws.send(hello(me + " tool", token))
        await ws.send(json.dumps(frame))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), wait))
            if m.get("type") in ("device_result", "devices"):
                return m


def main():
    from backtalk.config import CFG, peer_token
    args = sys.argv[1:]
    if not args or (args[0] != "--list" and len(args) != 2):
        sys.exit(__doc__)
    tok = peer_token()
    if not tok:
        sys.exit("no peer token (env JARVIS_PEER_TOKEN, or the keyring item service <peer_token_slot> user token)")
    url = f"ws://127.0.0.1:{CFG.get('web', {}).get('port', 8792)}"
    me = CFG.get("peer_name") or CFG["name"]
    if args[0] == "--list":
        live = set(asyncio.run(ask(url, tok, me, {"type": "devices"}))["connected"])
        try:
            with open(os.path.join(CFG["agent_dir"], ".backtalk", "devices.json")) as f:
                devs = json.load(f)
        except (OSError, ValueError):
            devs = {}
        seen = set()
        for d in devs.values():
            n = d.get("name", "?")
            if n in live and n not in seen:
                seen.add(n)
                caps = d.get("caps") or {}
                print(f"{n}: role {caps.get('role', '?')}, actions "
                      + (", ".join(caps.get("actions") or []) or "none (app too old)"))
        for n in sorted(live - seen):
            print(f"{n}: no actions")
        return
    try:
        frame = json.loads(args[1])
    except ValueError as e:
        sys.exit(f"not JSON: {e}")
    r = asyncio.run(ask(url, tok, me, {"type": "device", "device": args[0], "frame": frame}))
    print(r.get("text", ""))
    sys.exit(0 if r.get("ok") else 1)


if __name__ == "__main__":
    main()
