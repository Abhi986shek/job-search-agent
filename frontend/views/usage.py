import streamlit as st

import api_client as api

st.title("API usage")
days = st.slider("Period (days)", 1, 90, 30)
data = api.call(api.get, "/usage", params={"days": days})
if data:
    st.subheader("Totals")
    st.dataframe(data["totals"], hide_index=True, width="stretch")
    st.caption("PredictLeads discovery credits are estimated (billed per returned job). "
               "Check the real number with the request log below.")
    st.subheader("Last 100 calls")
    st.dataframe([{k: r[k] for k in ("called_at", "source", "endpoint", "status_code", "credits_used", "note")}
                  for r in data["recent"]], hide_index=True, width="stretch")

st.subheader("PredictLeads request log")
since = st.date_input("Since")
if st.button("Load log (verifies real credit cost)"):
    res = api.call(api.get, "/predictleads/request-logs", params={"since": since.isoformat()})
    if res:
        if res.get("error"):
            st.error(res["error"])
        else:
            st.dataframe(res.get("items") or [], width="stretch")
