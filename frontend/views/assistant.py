import uuid

import streamlit as st

import api_client as api

st.title("Assistant")
st.caption("Ask in plain words, e.g. 'check my inputs', 'search backend jobs in Bengaluru', 'match my jobs', "
           "'draft an email for job 12'. It prepares work; approvals and sending stay with you.")


def load_conversation(session_id: str) -> None:
    """Show a saved conversation. Its text is also loaded back into the agent when the next message is sent."""
    saved = api.call(api.get, f"/agent/sessions/{session_id}/messages") or []
    st.session_state.chat_session = session_id
    st.session_state.chat = [{"role": m["role"], "content": m["content"], "tools": m.get("tools")} for m in saved]


if "chat_session" not in st.session_state:
    # Opening the page after a restart: reopen the most recent saved conversation instead of an empty one.
    latest = api.call(api.get, "/agent/sessions") or []
    if latest:
        load_conversation(latest[0]["session_id"])
    else:
        st.session_state.chat_session = uuid.uuid4().hex
        st.session_state.chat = []

sessions = api.call(api.get, "/agent/sessions") or []
options = [s["session_id"] for s in sessions]
if st.session_state.chat_session not in options:
    options.insert(0, st.session_state.chat_session)  # the current chat is listed even before its first message
titles = {s["session_id"]: f"{s['title'] or 'New conversation'} ({s['last_at'].replace('T', ' ')})" for s in sessions}
titles.setdefault(st.session_state.chat_session, "New conversation")

c1, c2 = st.columns([3, 1])
picked = c1.selectbox("Past conversations", options, index=options.index(st.session_state.chat_session),
                      format_func=lambda sid: titles.get(sid, "New conversation"))
if picked != st.session_state.chat_session:
    load_conversation(picked)
    st.rerun()

if c2.button("New conversation"):
    api.call(api.post, "/agent/reset", {"session_id": st.session_state.chat_session, "message": "reset"})
    st.session_state.chat_session = uuid.uuid4().hex
    st.session_state.chat = []
    st.rerun()

for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("tools"):
            st.caption("Tools used: " + ", ".join(msg["tools"]))

prompt = st.chat_input("Message the assistant")
if prompt:
    st.session_state.chat.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        res = api.call(api.post, "/agent/chat", {"session_id": st.session_state.chat_session, "message": prompt},
                       timeout=api.LONG_TIMEOUT, spinner="Working...")
        if res:
            st.markdown(res["reply"])
            if res.get("tools_used"):
                st.caption("Tools used: " + ", ".join(res["tools_used"]))
            st.session_state.chat.append({"role": "assistant", "content": res["reply"], "tools": res.get("tools_used")})
