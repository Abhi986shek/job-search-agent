import streamlit as st

import api_client as api

st.title("Saved jobs")

c1, c2, c3 = st.columns(3)
status = c1.selectbox("Status", ["", "new", "shortlisted", "applied", "rejected", "archived"],
                      format_func=lambda x: x or "any")
source = c2.selectbox("Source", ["", "predictleads", "serpapi", "adzuna", "freehire", "ats", "guidance"],
                      format_func=lambda x: x or "any")
text = c3.text_input("Title, company or location")

data = api.call(api.get, "/jobs", params={k: v for k, v in {"status": status, "source": source, "q": text}.items() if v})
if not data:
    st.stop()
st.caption(f"{data['total']} jobs")

# Jobs that may be the same posting but were not merged automatically. Merge is a button you click.
dups = api.call(api.get, "/jobs/duplicates") or []
if dups:
    with st.expander(f"Possible duplicates ({len(dups)})"):
        st.caption("Same company, similar title, a city in common. Merge keeps the older job and moves "
                   "its sources, matches, CVs, contacts and outreach onto it.")
        for p in dups:
            a, b = p["job_a"], p["job_b"]
            d1, d2, d3 = st.columns([6, 1, 1])
            d1.write(f"**#{a['id']}** {a['title']} ({a.get('location') or '-'}; {', '.join(a['source_names'])})  \n"
                     f"**#{b['id']}** {b['title']} ({b.get('location') or '-'}; {', '.join(b['source_names'])})  \n"
                     f"{a.get('company') or ''} - {int(p['similarity'] * 100)}% similar titles")
            if d2.button("Merge", key=f"merge_{a['id']}_{b['id']}", help=f"Merge #{b['id']} into #{a['id']}"):
                if api.call(api.post, f"/jobs/{a['id']}/merge", {"merge_job_id": b["id"]}):
                    st.rerun()
            if d3.button("Not same", key=f"dismiss_{a['id']}_{b['id']}", help="Stop suggesting this pair"):
                if api.call(api.post, "/jobs/duplicates/dismiss", {"job_a": a["id"], "job_b": b["id"]}):
                    st.rerun()

st.dataframe([{"ID": j["id"], "Status": j["status"], "Title": j["title"], "Company": j["company"],
               "Location": j["location"], "Posted": j.get("posted_text") or "", "Via": ", ".join(j["via"]),
               "Sources": ", ".join(j["source_names"]), "Apply": j["apply_url"]} for j in data["items"]],
             hide_index=True, width="stretch",
             column_config={"Apply": st.column_config.LinkColumn("Apply", display_text="Open")})

ids = [j["id"] for j in data["items"]]
if not ids:
    st.stop()
job_id = st.selectbox("Open a job", ids, format_func=lambda i: next(
    f"#{j['id']} {j['title']} - {j['company']}" for j in data["items"] if j["id"] == i))
job = api.call(api.get, f"/jobs/{job_id}")
if job:
    st.subheader(f"{job['title']} - {job.get('company') or ''}")
    st.caption(f"{job.get('location') or ''} | {job.get('employment_type') or ''} | {job.get('salary_text') or ''}")
    a1, a2, a3 = st.columns(3)
    new_status = a1.selectbox("Change status", ["new", "shortlisted", "applied", "rejected", "archived"],
                              index=["new", "shortlisted", "applied", "rejected", "archived"].index(job["status"]))
    if a1.button("Save status"):
        api.call(api.patch, f"/jobs/{job_id}", {"status": new_status}, success="Saved.")
    if job.get("apply_url"):
        a2.link_button("Open apply link", job["apply_url"])
    if "predictleads" in job["source_names"] and a3.button("Fetch full description (1 PredictLeads credit)"):
        if api.call(api.post, f"/jobs/{job_id}/predictleads-details", timeout=120):
            st.rerun()
    st.markdown(job.get("description") or "_No description. Paste one under My job links, or open the apply link._")
    with st.expander("Sources"):
        for s in job["sources"]:
            st.write(f"{s['source']} via {s.get('via') or '-'}: {s.get('source_url') or ''}")
