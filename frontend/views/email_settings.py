from datetime import datetime, time

import streamlit as st

import api_client as api

st.title("Email and availability")

st.subheader("Your personal Gmail")
status = api.call(api.get, "/email/status") or {}
acct = status.get("account")
if acct:
    st.success(f"Connected: {acct['email_address']} via {acct['provider']}. "
               f"Sent in the last 24 hours: {status['sent_last_24h']} of {status['daily_cap']}.")
    if st.button("Disconnect"):
        api.call(api.delete, "/email/account")
        st.rerun()
else:
    st.info("Not connected.")
c1, c2 = st.columns(2)
with c1:
    st.markdown("**Gmail sign-in (recommended)**")
    st.caption("Needs GMAIL_OAUTH_CLIENT_FILE in job_agent/.env. A Google sign-in window opens on this computer.")
    if st.button("Connect Gmail", disabled=not status.get("gmail_client_file_ready")):
        if api.call(api.post, "/email/connect/gmail", timeout=api.LONG_TIMEOUT,
                    spinner="Finish the Google sign-in in your browser..."):
            st.rerun()
    if not status.get("gmail_client_file_ready"):
        st.caption("OAuth client file not found. See README, section 'Gmail setup'.")
with c2:
    st.markdown("**SMTP with an app password (fallback)**")
    st.caption("Needs SMTP_USERNAME and SMTP_APP_PASSWORD in job_agent/.env.")
    if st.button("Use SMTP", disabled=not status.get("smtp_configured")):
        if api.call(api.post, "/email/connect/smtp"):
            st.rerun()

st.subheader("Availability for interview replies")
st.caption("When someone asks for a call, reply drafts propose only these slots.")
with st.form("slot", clear_on_submit=True):
    s1, s2, s3, s4 = st.columns(4)
    day = s1.date_input("Day")
    start = s2.time_input("From", time(10, 0))
    end = s3.time_input("To", time(11, 0))
    tz = s4.text_input("Time zone", "Asia/Kolkata")
    if st.form_submit_button("Add slot"):
        api.call(api.post, "/availability", {"starts_at": datetime.combine(day, start).isoformat(),
                                             "ends_at": datetime.combine(day, end).isoformat(), "timezone": tz})
for s in api.call(api.get, "/availability") or []:
    a1, a2 = st.columns([5, 1])
    a1.write(f"{s['starts_at']} to {s['ends_at']} ({s['timezone']})")
    if a2.button("Delete", key=f"sl{s['id']}"):
        api.call(api.delete, f"/availability/{s['id']}")
        st.rerun()
