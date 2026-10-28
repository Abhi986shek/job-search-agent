import streamlit as st

import api_client as api

st.title("Job search")

tab_search, tab_company, tab_ats = st.tabs(["Search a role", "One company (PredictLeads)", "ATS boards"])

with tab_search:
    status = api.call(api.get, "/status") or {}
    roles = [r for r in (api.call(api.get, "/roles", params={"status": "confirmed"}) or [])]
    role_opts = {None: "No role (use the query below)"} | {r["id"]: f"#{r['id']} {r['title']}" for r in roles}
    role_id = st.selectbox("Confirmed target role", list(role_opts), format_func=role_opts.get)
    c1, c2, c3 = st.columns(3)
    query = c1.text_input("Query", placeholder="python backend developer", help="Defaults to the role title")
    location = c2.text_input("City", placeholder="Bengaluru", help="Used by SerpApi and Adzuna")
    country = c3.text_input("Country or state for PredictLeads", "India")

    st.markdown("**Sources**")
    s1, s2, s3, s4 = st.columns(4)
    labels = {"predictleads": s1, "serpapi": s2, "adzuna": s3, "freehire": s4}
    chosen = []
    for key, col in labels.items():
        info = status.get(key) or {}
        ok = bool(info.get("configured"))
        if col.checkbox(info.get("label", key), value=ok, disabled=not ok, key=f"src_{key}",
                        help=None if ok else "Not configured in job_agent/.env"):
            chosen.append(key)
    st.caption("Saved ATS boards are always included. PredictLeads discovery may bill per returned job; "
               "the per-search limit is set by PREDICTLEADS_DISCOVER_LIMIT.")
    c4, c5, c6 = st.columns(3)
    days = c4.number_input("Posted within (days)", 1, 365, 30)
    limit = c5.number_input("Max jobs per source", 1, 100, 25)
    kw = c6.checkbox("Filter PredictLeads results by title words", value=True)

    if st.button("Search", type="primary"):
        res = api.call(api.post, "/searches", {
            "target_role_id": role_id, "query": query, "location": location, "country": country,
            "sources": chosen, "max_days_old": int(days), "limit_per_source": int(limit),
            "keyword_filter_predictleads": kw}, timeout=api.LONG_TIMEOUT, spinner="Searching...")
        if res:
            st.session_state.last_search = res

    res = st.session_state.get("last_search")
    if res is None:
        # After a restart the browser has no last result. Reload the most recent saved search from the database.
        latest = api.call(api.get, "/searches", params={"limit": 1}) or []
        if latest:
            s = latest[0]
            summary = s.get("results_summary") or {}
            found = api.call(api.get, "/jobs", params={"search_id": s["id"], "limit": 500}) or {}
            res = {"search_id": s["id"], "query": s["query"], "onet_codes": summary.get("onet_codes") or [],
                   "sources": summary.get("sources") or [], "jobs": found.get("items") or []}
            st.session_state.last_search = res
    if res:
        st.caption("Showing the latest saved search. Run a new search to replace it; all jobs stay saved.")
        st.subheader(f"Search #{res['search_id']}: {res['query']}")
        st.caption("O*NET codes: " + ", ".join(res.get("onet_codes") or []))
        st.dataframe([{"Source": s["label"], "Status": s["status"], "Fetched": s["fetched"], "New": s["new"],
                       "Merged into existing": s["merged"], "Note": s["message"]} for s in res["sources"]],
                     hide_index=True, width="stretch")
        st.dataframe([{"ID": j["id"], "Title": j["title"], "Company": j["company"], "Location": j["location"],
                       "Via": ", ".join(j["via"]), "Sources": ", ".join(j["source_names"]),
                       "Apply": j["apply_url"]} for j in res["jobs"]],
                     hide_index=True, width="stretch",
                     column_config={"Apply": st.column_config.LinkColumn("Apply", display_text="Open")})

with tab_company:
    domain = st.text_input("Company domain", placeholder="razorpay.com")
    if st.button("Get open jobs (1 PredictLeads credit)") and domain:
        res = api.call(api.post, "/companies/jobs", {"domain": domain, "limit": 100}, timeout=120,
                       spinner="Asking PredictLeads...")
        if res:
            s = res["summary"]
            (st.success if s["status"] == "ok" else st.error)(f"{s['status']}: {s['fetched']} jobs. {s['message']}")
            st.dataframe([{"ID": j["id"], "Title": j["title"], "Location": j["location"], "Apply": j["apply_url"]}
                          for j in res["jobs"]], hide_index=True, width="stretch",
                         column_config={"Apply": st.column_config.LinkColumn("Apply", display_text="Open")})

with tab_ats:
    st.markdown("Free public job boards. The board token is the company slug in its careers URL: "
                "`boards.greenhouse.io/<token>`, `jobs.lever.co/<token>`, `jobs.ashbyhq.com/<token>`.")
    with st.form("ats", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        provider = c1.selectbox("Provider", ["greenhouse", "lever", "ashby"])
        token = c2.text_input("Board token")
        company = c3.text_input("Company name")
        if st.form_submit_button("Add board") and token:
            res = api.call(api.post, "/ats-boards", {"provider": provider, "board_token": token.strip(),
                                                     "company_name": company}, timeout=120)
            if res:
                chk = res.get("check") or {}
                (st.success if chk.get("status") == "ok" else st.error)(
                    f"{chk.get('status')}: {chk.get('fetched', 0)} jobs. {chk.get('message', '')}")
    for b in api.call(api.get, "/ats-boards") or []:
        b1, b2, b3 = st.columns([5, 1, 1])
        b1.write(f"{b['company_name']} ({b['provider']}/{b['board_token']}) - last checked {b['last_checked_at']}")
        if b2.button("Refresh", key=f"rb{b['id']}"):
            res = api.call(api.post, f"/ats-boards/{b['id']}/refresh", timeout=120)
            if res:
                st.info(f"{res['status']}: {res['fetched']} jobs, {res['new']} new")
        if b3.button("Delete", key=f"db{b['id']}"):
            api.call(api.delete, f"/ats-boards/{b['id']}")
            st.rerun()
