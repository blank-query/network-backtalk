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
"""TIMERS THAT LIVE HERE, NOT ON A PHONE: listed, cancelled, and rung on
whichever device they name. The running voice line (main.py) shows them
on that device's face and, when one is due, announces it there and rings
the device until someone stops it (apps with the ring action).

  python -m backtalk.timer add "<device>" <seconds> "<label>" [--buzz "<device>"]
                                    --buzz: also a notification on that
                                    device when it rings (sir's phone:
                                    his watch buzzes with it)
  python -m backtalk.timer          list them, with time left
  python -m backtalk.timer cancel <label or number>

One that's ringing stops with a tap on it, after a minute, or with
python -m backtalk.device "<device>" '{"do": "ring_stop"}'.

The file is <agent_dir>/.backtalk/timers.json (BACKTALK_CONFIG picks the
instance).
"""
import contextlib
import fcntl
import json
import os
import sys
import time


def path() -> str:
    from backtalk.config import CFG
    return os.path.join(CFG["agent_dir"], ".backtalk", "timers.json")


@contextlib.contextmanager
def locked(p: str):
    """The list, under a lock (the voice line removes timers as they ring);
    whatever's left in it at the end is saved."""
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        items = load(p)
        before = json.dumps(items)
        yield items
        if json.dumps(items) != before:
            tmp = p + ".tmp"
            with open(tmp, "w") as f:
                json.dump(items, f, indent=1)
            os.replace(tmp, p)


def load(p: str) -> list:
    try:
        with open(p) as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def left(at: float, now: float) -> str:
    s = max(0, round(at - now))
    return f"{s // 3600}h {s % 3600 // 60}m {s % 60}s" if s >= 3600 else f"{s // 60}m {s % 60}s"


def run(p: str, args: list, now: float | None = None) -> str:
    now = time.time() if now is None else now
    cmd, rest = (args[0], args[1:]) if args else ("list", [])
    with locked(p) as items:
        if cmd == "add":
            buzz = None
            if "--buzz" in rest:
                i = rest.index("--buzz")
                buzz, rest = rest[i + 1], rest[:i] + rest[i + 2:]
            if len(rest) < 2 or not rest[1].replace(".", "", 1).isdigit():
                raise ValueError("add needs a device, seconds, and a label")
            label = " ".join(rest[2:]).strip() or "timer"
            items.append({"device": rest[0], "label": label[:40], "at": now + float(rest[1]),
                          **({"buzz": buzz} if buzz else {})})
        elif cmd == "cancel":
            what = " ".join(rest).strip()
            keep = [t for i, t in enumerate(items, 1)
                    if not (str(i) == what or t["label"].casefold() == what.casefold())]
            if len(keep) == len(items):
                raise ValueError(f"no timer {what!r}")
            items[:] = keep
        elif cmd != "list":
            raise ValueError(f"unknown command {cmd!r}")
        out = "\n".join(f"{i}. {t['label']} on {t['device']}: {left(t['at'], now)} left"
                        for i, t in enumerate(items, 1)) or "(no timers)"
    return out


def due(p: str, now: float | None = None) -> list:
    """Take the timers that are due off the list (the voice line rings them)."""
    now = time.time() if now is None else now
    with locked(p) as items:
        hit = [t for t in items if t["at"] <= now]
        items[:] = [t for t in items if t["at"] > now]
    return hit


def main():
    try:
        print(run(path(), sys.argv[1:]))
    except (ValueError, IndexError) as e:
        sys.exit(f"{e}\n{__doc__}")


if __name__ == "__main__":
    main()
