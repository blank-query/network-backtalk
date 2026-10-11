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
"""THE SESSION TO-DO LIST: what this assistant has going in its current
session, for the person's swipe-down task view. The agent keeps it
current with this CLI; the bridge publishes it to every device within a
second (web.py's tasks frame), with the running background tasks added
to IN PROGRESS by itself.

  python -m backtalk.todo                   list it, numbered
  python -m backtalk.todo add "text"        NOT STARTED: discussed, not begun
  python -m backtalk.todo wait "text"|N     WAITING ON SIR: a decision he owes
  python -m backtalk.todo start "text"|N    IN PROGRESS: being worked on now
  python -m backtalk.todo done N [N...]     finished or dropped: off the list
  python -m backtalk.todo clear             empty it

A number moves an existing item; text adds a new one. The file is
<agent_dir>/.backtalk/todo.json (BACKTALK_CONFIG picks the instance).
"""
import json
import os
import sys
import time

STATES = {"add": "todo", "wait": "waiting", "start": "progress"}
LABEL = {"waiting": "WAITING ON SIR", "progress": "IN PROGRESS", "todo": "NOT STARTED"}


def path() -> str:
    from backtalk.config import CFG
    return os.path.join(CFG["agent_dir"], ".backtalk", "todo.json")


def load(p: str) -> list:
    try:
        with open(p) as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def save(p: str, items: list):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items, f, indent=1)
    os.replace(tmp, p)


def run(p: str, args: list) -> str:
    items = load(p)
    cmd, rest = (args[0], args[1:]) if args else ("list", [])
    if cmd in STATES:
        what = " ".join(rest).strip()
        if not what:
            raise ValueError(f"{cmd} needs some text or an item number")
        if what.isdigit():
            items[int(what) - 1]["state"] = STATES[cmd]
        else:
            items.append({"text": what, "state": STATES[cmd], "since": time.strftime("%H:%M")})
    elif cmd == "done":
        drop = {int(n) - 1 for n in rest}
        if not drop or max(drop) >= len(items) or min(drop) < 0:
            raise ValueError("done needs item numbers from the list")
        items = [it for i, it in enumerate(items) if i not in drop]
    elif cmd == "clear":
        items = []
    elif cmd != "list":
        raise ValueError(f"unknown command {cmd!r}")
    if cmd != "list":
        save(p, items)
    return "\n".join(f"{i}. [{LABEL.get(it.get('state'), 'NOT STARTED')}] {it.get('text', '')}"
                     for i, it in enumerate(items, 1)) or "(empty)"


def main():
    try:
        print(run(path(), sys.argv[1:]))
    except (ValueError, IndexError) as e:
        sys.exit(f"{e}\n{__doc__}")


if __name__ == "__main__":
    main()
