import csv
import io

import streamlit as st

import api_client as api

st.title("My job links")
st.caption("Jobs you found yourself on Naukri, LinkedIn or anywhere. The app never opens these pages; paste the "
           "description so matching and CV tailoring can use it.")

tab_one, tab_bulk = st.tabs(["Add one", "Add many"])
with tab_one:
    with st.form("one", clear_on_submit=True):
        url = st.text_input("Job URL")
        c1, c2, c3 = st.columns(3)
        title = c1.text_input("Title")
        company = c2.text_input("Company")
        location = c3.text_input("Location")
        desc = st.text_area("Job description (paste it here)", height=200)
        note = st.text_input("Your note")
        if st.form_submit_button("Save link", type="primary") and url:
            if api.call(api.post, "/guidance-urls", {"items": [{"url": url, "title": title, "company": company,
                                                                 "location": location, "pasted_description": desc,
                                                                 "note": note}]}):
                st.success("Saved. It now appears in Saved jobs.")

with tab_bulk:
    text = st.text_area("One URL per line", height=150)
    upload = st.file_uploader("Or a .txt / .csv file (CSV columns: url, title, company, location, note)",
                              type=["txt", "csv"])
    if st.button("Save all", type="primary"):
        items = [{"url": line.strip()} for line in text.splitlines() if line.strip()]
        if upload:
            raw = upload.getvalue().decode("utf-8-sig", errors="replace")
            if upload.name.lower().endswith(".csv") and "url" in raw.splitlines()[0].lower():
                for row in csv.DictReader(io.StringIO(raw)):
                    if row.get("url"):
                        items.append({k: (row.get(k) or "").strip() for k in ("url", "title", "company", "location", "note")})
            else:
                items += [{"url": line.strip()} for line in raw.splitlines() if line.strip()]
        if items:
            res = api.call(api.post, "/guidance-urls", {"items": items[:200]})
            if res:
                st.success(f"Saved {len(res)} link(s), {sum(r['created'] for r in res)} new.")

rows = api.call(api.get, "/guidance-urls") or []
for g in rows:
    g1, g2 = st.columns([6, 1])
    note_line = f"  \n_{g['note']}_" if g.get("note") else ""
    g1.markdown(f"**{g.get('title') or 'Untitled'}** - {g.get('company') or ''} ({g['portal']})  \n{g['url']}{note_line}")
    if g2.button("Delete", key=f"g{g['id']}"):
        api.call(api.delete, f"/guidance-urls/{g['id']}")
        st.rerun()
