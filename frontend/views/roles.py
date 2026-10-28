import streamlit as st

import api_client as api

st.title("Target roles")
st.caption("Only confirmed roles are used for searching. PredictLeads searches by O*NET code, so check the codes.")

if st.button("Propose roles from my profile"):
    res = api.call(api.post, "/roles/propose", timeout=api.LONG_TIMEOUT, spinner="Thinking about fitting roles...")
    if res:
        for r in res:
            st.info(f"{r['title']}: {r.get('why')}")

with st.expander("Add a role", expanded=False):
    title = st.text_input("Role title", placeholder="Backend Engineer")
    suggested = []
    all_codes = []
    if title.strip():
        data = api.call(api.get, "/onet/suggest", params={"title": title}) or {}
        suggested = [s["code"] for s in data.get("suggested") or []]
        all_codes = data.get("all") or []
    names = {c["code"]: f"{c['code']} {c['name']}" for c in all_codes}
    codes = st.multiselect("O*NET codes", options=list(names) or suggested, default=suggested,
                           format_func=lambda c: names.get(c, c))
    c1, c2, c3 = st.columns(3)
    seniority = c1.selectbox("Seniority", ["", "junior", "mid", "senior", "lead", "manager"])
    locations = c2.text_input("Locations (comma separated)", placeholder="Bengaluru, Pune")
    remote = c3.checkbox("Remote is fine")
    if st.button("Save role", type="primary") and title.strip():
        if api.call(api.post, "/roles", {"title": title, "seniority": seniority, "remote_ok": remote,
                                         "locations": [x.strip() for x in locations.split(",") if x.strip()],
                                         "onet_codes": codes, "status": "confirmed"}):
            st.success("Role saved and confirmed.")
            st.rerun()

roles = api.call(api.get, "/roles") or []
if not roles:
    st.info("No roles yet.")
for r in roles:
    badge = {"confirmed": "Confirmed", "proposed": "Proposed", "rejected": "Rejected"}[r["status"]]
    with st.container(border=True):
        st.markdown(f"**#{r['id']} {r['title']}** - {badge}  \n"
                    f"{r.get('seniority') or ''} | {', '.join(r.get('locations') or []) or 'any location'}"
                    f"{' | remote ok' if r['remote_ok'] else ''}  \nO*NET: {', '.join(r.get('onet_codes') or []) or 'none'}")
        c1, c2, c3, c4 = st.columns(4)
        if r["status"] != "confirmed" and c1.button("Confirm", key=f"c{r['id']}", type="primary"):
            api.call(api.patch, f"/roles/{r['id']}", {"status": "confirmed"})
            st.rerun()
        if r["status"] != "rejected" and c2.button("Reject", key=f"r{r['id']}"):
            api.call(api.patch, f"/roles/{r['id']}", {"status": "rejected"})
            st.rerun()
        new_codes = c3.text_input("Edit O*NET codes", ", ".join(r.get("onet_codes") or []), key=f"o{r['id']}",
                                  label_visibility="collapsed")
        if c3.button("Save codes", key=f"sc{r['id']}"):
            api.call(api.patch, f"/roles/{r['id']}",
                     {"onet_codes": [x.strip() for x in new_codes.split(",") if x.strip()]}, success="Codes saved.")
        if c4.button("Delete", key=f"d{r['id']}"):
            api.call(api.delete, f"/roles/{r['id']}")
            st.rerun()
