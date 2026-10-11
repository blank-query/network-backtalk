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
"""LET A DEVICE PICK THIS ASSISTANT: issue it a token of its own, never
the peer secret. Run only on the owner's explicit say-so.

  python -m backtalk.grant "<device name>" [--pi ws://host:port]
      a new random token for that device: only its hash stays here
      (<agent_dir>/.backtalk/device_tokens.json, which this bridge checks
      on every connect when require_token is on); the token itself goes
      once, through the home bridge the device is connected to right now
      (--pi, default peer_link's url), as {"type": "grant", "assistant":
      {id, name, url, color, face}, "token"}. The device keeps it and
      offers this assistant in its picker. Not delivered = not kept.
  python -m backtalk.grant "<device name>" --revoke    its tokens stop working
  python -m backtalk.grant --list                      who holds one (no tokens shown)

Needs config "lan_url" (how a device reaches this bridge, e.g.
ws://<this machine's LAN address>:8792), and the peer token (to talk to
the home bridge). BACKTALK_CONFIG picks the instance.
"""
import asyncio
import hashlib
import json
import os
import re
import secrets
import sys
import time

import websockets


def tokens_path(cfg) -> str:
    return os.path.join(cfg["agent_dir"], ".backtalk", "device_tokens.json")


def load(p: str) -> dict:
    try:
        with open(p) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(p: str, d: dict):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, p)


def assistant(cfg) -> dict:
    name = cfg.get("peer_name") or cfg["name"]
    return {"id": re.sub(r"\W+", "-", name.lower()).strip("-"), "name": name,
            "url": cfg.get("lan_url") or "", "color": cfg.get("identity_color") or "",
            "face": cfg.get("identity_face") or ""}


async def deliver(pi_url: str, peer_tok: str, me: str, device: str, frame: dict) -> bool:
    from backtalk.say import MAX, hello
    async with websockets.connect(pi_url, max_size=MAX, open_timeout=10) as ws:
        await ws.send(hello(me, peer_tok))
        await ws.send(json.dumps({"type": "deliver", "device": device, "frame": frame}))
        while True:
            m = await asyncio.wait_for(ws.recv(), 10)
            if isinstance(m, str) and json.loads(m).get("type") == "delivered":
                return bool(json.loads(m).get("ok"))


def grant(cfg, device: str, pi_url: str, peer_tok: str) -> str:
    a = assistant(cfg)
    if not a["url"]:
        raise SystemExit("set \"lan_url\" in this instance's config first")
    p, tok = tokens_path(cfg), secrets.token_urlsafe(32)
    d = load(p)
    h = hashlib.sha256(tok.encode()).hexdigest()
    d[h] = {"device": device, "issued": time.strftime("%Y-%m-%d %H:%M")}
    save(p, d)
    try:
        ok = asyncio.run(deliver(pi_url, peer_tok, a["name"], device,
                                 {"type": "grant", "assistant": a, "token": tok}))
    except Exception as e:
        ok, why = False, repr(e)
    else:
        why = "it isn't connected to the home bridge right now"
    if not ok:
        d.pop(h, None)
        save(p, d)
        raise SystemExit(f"not granted: {why} (no token kept)")
    return f"{device} can now pick {a['name']}"


def revoke(cfg, device: str) -> str:
    p = tokens_path(cfg)
    d = load(p)
    keep = {h: e for h, e in d.items() if e.get("device") != device}
    save(p, keep)
    return f"revoked {len(d) - len(keep)} token(s) for {device}"


def main():
    from backtalk.config import CFG, peer_token
    args = sys.argv[1:]
    if args == ["--list"]:
        print("\n".join(f"{e.get('device')} (issued {e.get('issued')})"
                        for e in load(tokens_path(CFG)).values()) or "(none)")
        return
    if not args or args[0].startswith("-"):
        sys.exit(__doc__)
    device = args[0]
    if "--revoke" in args:
        print(revoke(CFG, device))
        return
    pi = args[args.index("--pi") + 1] if "--pi" in args else (CFG.get("peer_link") or {}).get("url")
    if not pi:
        sys.exit("no home bridge: pass --pi ws://host:port")
    tok = peer_token()
    if not tok:
        sys.exit("no peer token (env JARVIS_PEER_TOKEN, or the keyring item service backtalk-peer user token)")
    print(grant(CFG, device, pi, tok))


if __name__ == "__main__":
    main()
