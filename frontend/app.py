"""Streamlit frontend for the Job Search and CV Agent. Talks only to the backend (api_client.py).

Run from the project root:  bash run.sh  (starts backend and frontend)
"""

import streamlit as st

st.set_page_config(page_title="Job Search Agent", page_icon=":material/work:", layout="wide")

pages = {
    "Start": [
        st.Page("views/home.py", title="Status", icon=":material/dashboard:", default=True),
        st.Page("views/assistant.py", title="Assistant", icon=":material/chat:"),
    ],
    "1. You": [
        st.Page("views/profile.py", title="Profile inputs", icon=":material/person:"),
        st.Page("views/roles.py", title="Target roles", icon=":material/flag:"),
    ],
    "2. Jobs": [
        st.Page("views/search.py", title="Job search", icon=":material/search:"),
        st.Page("views/jobs.py", title="Saved jobs", icon=":material/list:"),
        st.Page("views/guidance.py", title="My job links", icon=":material/link:"),
    ],
    "3. Apply": [
        st.Page("views/matches.py", title="Matches and CVs", icon=":material/description:"),
        st.Page("views/outreach.py", title="Outreach", icon=":material/mail:"),
    ],
    "Settings": [
        st.Page("views/email_settings.py", title="Email and availability", icon=":material/settings:"),
        st.Page("views/usage.py", title="API usage", icon=":material/monitoring:"),
    ],
}

st.navigation(pages).run()
