# Run: .venv/bin/python tests/check_helper_traffic.py
# Self-check: a background helper's traffic (messages with a parent_tool_use_id,
# never a ResultMessage) is not a turn. An ask still goes out at once, a stop
# does not interrupt (that would kill the helper), and a turn that goes silent
# for STUCK_AFTER is released (the overnight hang, 2026-10-11), but not while
# a tool call is in flight or a background task runs (a 3-minute tool call
# on Friday, 2026-10-11).
import asyncio, sys
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), ".."))
from claude_agent_sdk import AssistantMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage
from claude_agent_sdk.types import StreamEvent
from backtalk import brain as B

class Bus:
    def __getattr__(s, n): return lambda *a, **k: None
class Mouth:
    speaking = False
    def __getattr__(s, n): return lambda *a, **k: None
class Client:
    def __init__(s): s.q = asyncio.Queue(); s.queries = []; s.interrupts = 0
    async def query(s, u): s.queries.append(u)
    async def interrupt(s): s.interrupts += 1
    def receive_messages(s):
        async def gen():
            while True: yield await s.q.get()
        return gen()

P = "toolu_helper"
helper = [StreamEvent(uuid="u", session_id="s", parent_tool_use_id=P,
                      event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Helper text. "}}),
          AssistantMessage(content=[TextBlock("Helper says hi.")], model="m", parent_tool_use_id=P),
          UserMessage(content="tool result", parent_tool_use_id=P)]

async def main():
    b = B.WarmBrain(mouth=Mouth(), bus=Bus())
    b._client = c = Client(); b._start_reader()
    for m in helper: c.q.put_nowait(m)
    await asyncio.sleep(1.2)
    assert not b.turn_active, "helper traffic opened a turn"
    b.ask("sir asks")
    await asyncio.sleep(0.05)
    assert c.queries == ["sir asks"], f"ask was queued, not sent: {c.queries}"
    b._turn_active = False                      # the ask's own turn, set aside
    await b.interrupt()
    assert c.interrupts == 0 and not b._discard_until_result, "stop with no main turn interrupted"
    b._turn_active, b._last_main = True, 0.0    # a phantom turn, silent for ages
    b.ask("queued behind it")
    assert c.queries == ["sir asks"]
    await b.interrupt()
    await asyncio.sleep(0.05)
    assert c.interrupts == 0 and c.queries[-1] == "queued behind it", "stuck turn not released"
    # a long tool call: sent, no result yet, silent past STUCK_AFTER
    c.q.put_nowait(AssistantMessage(content=[ToolUseBlock("toolu_main", "Bash", {})], model="m"))
    await asyncio.sleep(0.05)
    b._last_main = 0.0
    assert not b._release_if_stuck() and b.turn_active, "a running tool call was released"
    c.q.put_nowait(UserMessage(content=[ToolResultBlock("toolu_main")]))
    await asyncio.sleep(0.05)
    b._active_tasks, b._last_main = {"task1"}, 0.0
    assert not b._release_if_stuck() and b.turn_active, "a running background task was released"
    b._active_tasks, b._last_main = set(), 0.0
    assert b._release_if_stuck(), "silent turn with nothing running not released"
    print("OK")
asyncio.run(main())
