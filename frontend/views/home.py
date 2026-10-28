import streamlit as st

import api_client as api

st.title("Status")

health = api.call(api.get, "/health")
if not health:
    st.stop()
st.success("Backend is running.")

status = api.call(api.get, "/status", spinner="Checking sources...")
if status:
    rows = []
    for key, val in status.items():
        if not isinstance(val, dict):
            continue
        state = "configured" if val.get("configured") else "not configured"
        if val.get("error"):
            state = f"error: {val['error']}"
        detail = ""
        if key == "predictleads" and val.get("quota") is not None:
            detail = f"{val.get('used')} of {val.get('quota')} credits used this month"
        elif key == "serpapi" and val.get("remaining") is not None:
            detail = f"{val.get('remaining')} searches left ({val.get('plan')})"
        elif key == "ats":
            detail = f"{val.get('boards', 0)} boards"
        elif key == "bedrock" and val.get("model_id"):
            detail = val["model_id"]
        rows.append({"Service": val.get("label") or key, "State": state, "Detail": detail})
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("Keys live in job_agent/.env. Restart the backend after editing it.")

st.subheader("How to use it")
st.markdown(
    """
1. **Profile inputs**: upload your CV and add notes, add LinkedIn, sync both GitHub accounts and tick the repos
   you really worked on, add manual projects. Then click **Build profile**.
2. **Target roles**: propose or add roles, check the O*NET codes, and **confirm** them.
3. **Job search**: search a confirmed role. Add ATS boards for companies you like.
   Save Naukri or other links you find yourself under **My job links**.
4. **Matches and CVs**: score and group jobs, review each proposed CV change, then generate DOCX and PDF.
5. **Outreach**: find a contact, draft, edit, approve, send from your Gmail. LinkedIn drafts you send yourself.
   Check replies and draft your next response.
"""
)
