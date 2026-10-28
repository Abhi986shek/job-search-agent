"""The job search assistant: a Strands agent on Bedrock with the @tool functions from tools/.

One agent per chat session, kept in memory. Every message is also saved to the database, so a past
conversation can be reopened after a restart: its earlier text is loaded back into the agent's context.
Approval actions (approve a CV change, reveal an Apollo email, send an email) are not tools, so the agent
can prepare work but never act on the user's behalf.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

from config import settings
from llm import get_model
from prompts import AGENT_SYSTEM_PROMPT as SYSTEM_PROMPT
from tools import ALL_TOOLS  # every @tool function, defined in tools/__init__.py
from utils import logger

_MAX_SESSIONS = 20
_MAX_RESTORED = 40  # most recent saved messages loaded back into a restarted conversation
_sessions: "OrderedDict[str, object]" = OrderedDict()
_lock = threading.Lock()


def _restored_messages(session_id: str) -> list[dict]:
    """Saved text of a past conversation, as Strands messages. Tool calls are not replayed, only the text.
    Roles must alternate and start with the user, so the list is trimmed to a valid start."""
    from db import repositories as repo

    saved = [m for m in repo.list_assistant_messages(session_id) if m["content"].strip()][-_MAX_RESTORED:]
    while saved and saved[0]["role"] != "user":
        saved = saved[1:]
    msgs, last = [], None
    for m in saved:
        if m["role"] == last:
            continue  # keep roles alternating
        msgs.append({"role": m["role"], "content": [{"text": m["content"]}]})
        last = m["role"]
    if msgs and msgs[-1]["role"] != "assistant":
        msgs = msgs[:-1]  # a trailing user message would be sent twice when the new turn arrives
    return msgs


def _new_agent(session_id: str):
    from strands import Agent

    return Agent(model=get_model(temperature=0.3, max_tokens=4000), tools=ALL_TOOLS,
                 system_prompt=SYSTEM_PROMPT, callback_handler=None, messages=_restored_messages(session_id))


def get_agent(session_id: str):
    with _lock:
        agent = _sessions.get(session_id)
        if agent is None:
            agent = _new_agent(session_id)
            _sessions[session_id] = agent
            while len(_sessions) > _MAX_SESSIONS:
                _sessions.popitem(last=False)
        else:
            _sessions.move_to_end(session_id)
        return agent


def reset(session_id: str) -> None:
    """Drop the in-memory agent. The saved conversation stays in the database."""
    with _lock:
        _sessions.pop(session_id, None)


def chat(session_id: str, message: str) -> dict:
    """Run one turn. Called from a worker thread by the /agent/chat route."""
    from db import repositories as repo

    if not settings.bedrock_configured:
        return {"reply": "Bedrock is not configured. Set BEDROCK_MODEL_ID and AWS_REGION in job_agent/.env.",
                "tools_used": []}
    agent = get_agent(session_id)
    before = len(agent.messages)
    result = agent(message)
    tools_used = []
    for msg in agent.messages[before:]:
        for block in msg.get("content") or []:
            if isinstance(block, dict) and "toolUse" in block:
                tools_used.append(block["toolUse"].get("name"))
    reply = str(result).strip()
    repo.add_assistant_message(session_id, "user", message)
    repo.add_assistant_message(session_id, "assistant", reply, tools_used)
    logger.info("agent turn ok, tools=%s", tools_used)
    return {"reply": reply, "tools_used": tools_used}
