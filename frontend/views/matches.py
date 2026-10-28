import streamlit as st
import streamlit.components.v1 as components

import api_client as api

st.title("Matches and CVs")

tab_match, tab_cv = st.tabs(["Score and group jobs", "Tailored CVs"])

with tab_match:
    c1, c2 = st.columns(2)
    limit = c1.number_input("How many recent jobs to score", 1, 200, 40)
    if c1.button("Score and group jobs", type="primary"):
        res = api.call(api.post, "/matches/run", {"limit": int(limit)}, timeout=api.LONG_TIMEOUT,
                       spinner="Scoring jobs against your profile...")
        if res:
            st.success(f"Scored {res['scored']} jobs into {len(res['groups'])} groups.")
            if res.get("remaining"):
                st.info(f"{res['remaining']} open jobs are not scored yet. Click again to score the next batch.")
    if c2.button("Regroup only"):
        api.call(api.post, "/matches/regroup", timeout=api.LONG_TIMEOUT, spinner="Grouping...", success="Regrouped.")

    data = api.call(api.get, "/matches") or {}
    groups = data.get("groups") or []
    if not data.get("matches"):
        st.info("No matches yet. Build your profile, search jobs, then score them.")
    for g in groups:
        with st.container(border=True):
            st.markdown(f"**Group #{g['id']}: {g['name']}** - {len(g['jobs'])} jobs  \n{g.get('summary') or ''}")
            with st.expander(f"Jobs in this group ({len(g['jobs'])})", expanded=False):
                for j in g["jobs"]:
                    r1, r2, r3 = st.columns([5, 2, 2])
                    place = f" | {j['location']}" if j.get("location") else ""
                    done = " | applied" if j.get("status") == "applied" else ""
                    r1.markdown(f"**{j['title']}** - {j.get('company') or ''}  \n"
                                f"Score {int(j['score'])}{place}{done}  \n"
                                f"<span style='opacity:.6'>Job #{j['id']}</span>", unsafe_allow_html=True)
                    if j.get("apply_url"):
                        r2.link_button("Apply", j["apply_url"], key=f"ap_{g['id']}_{j['id']}")
                    else:
                        r2.caption("No link")
                    if j.get("status") != "applied" and r3.button("Mark applied", key=f"ma_{g['id']}_{j['id']}"):
                        if api.call(api.patch, f"/jobs/{j['id']}", {"status": "applied"}, success="Marked as applied."):
                            st.rerun()
            if st.button("Propose CV changes for this group", key=f"pg{g['id']}"):
                if api.call(api.post, "/cv-versions", {"job_group_id": g["id"]}, timeout=api.LONG_TIMEOUT,
                            spinner="Drafting CV changes..."):
                    st.success("Proposals ready in the Tailored CVs tab.")
    if data.get("matches"):
        st.subheader("All scores")
        st.dataframe([{"Job": m["job_id"], "Score": m["score"], "Title": m["job"]["title"],
                       "Company": m["job"]["company"], "Group": m.get("job_group_id"),
                       "Biggest gap": (m.get("gaps") or [{}])[0].get("gap") if m.get("gaps") else ""}
                      for m in data["matches"]], hide_index=True, width="stretch")
        job_ids = [m["job_id"] for m in data["matches"]]
        pick = st.selectbox("A job that needs its own CV", job_ids,
                            format_func=lambda i: next(f"#{m['job_id']} {m['job']['title']}" for m in data["matches"]
                                                       if m["job_id"] == i))
        m = next(x for x in data["matches"] if x["job_id"] == pick)
        with st.expander("Why this score"):
            st.write("\n".join(f"- {r}" for r in m.get("reasons") or []))
            st.write("\n".join(f"- **{g.get('gap')}** ({g.get('severity')}): {g.get('reason')}" for g in m.get("gaps") or []))
        if st.button("Propose a CV just for this job"):
            if api.call(api.post, "/cv-versions", {"job_id": pick}, timeout=api.LONG_TIMEOUT,
                        spinner="Drafting CV changes..."):
                st.success("Proposals ready in the Tailored CVs tab.")

with tab_cv:
    # Header details that are not in the profile: contact, languages and interests, as in the CV layout.
    with st.expander("CV header details (contact, languages, interests)"):
        extras = api.call(api.get, "/cv-extras") or {}
        contact = extras.get("contact") or {}
        e1, e2 = st.columns(2)
        email = e1.text_input("Email", contact.get("email", ""))
        phone = e2.text_input("Phone", contact.get("phone", ""))
        location = e1.text_input("Location", contact.get("location", ""))
        linkedin = e2.text_input("LinkedIn", contact.get("linkedin", ""))
        langs_text = st.text_area("Languages (one per line: Name - level)", "\n".join(
            f"{x['name']} - {x.get('level', '')}" for x in extras.get("languages") or []))
        interests_text = st.text_area("Interests (one per line)", "\n".join(extras.get("interests") or []))
        st.markdown("**Photo**")
        st.caption("Shown at the top right of the CV. Use a JPG or PNG with your face clearly visible.")
        if extras.get("photo_saved"):
            st.success("A photo is saved and used in the CV preview and files.")
        photo_file = st.file_uploader("Choose a photo (JPG or PNG, up to 5 MB)", type=["jpg", "jpeg", "png"],
                                      key="cv_photo_file")
        ph1, ph2 = st.columns(2)
        if photo_file is not None and ph1.button("Save photo", key="cv_photo_save"):
            if api.call(api.request, "POST", "/cv-photo", files={"file": (photo_file.name, photo_file.getvalue())},
                        timeout=60, success="Photo saved. The CV preview uses it now."):
                st.rerun()
        if extras.get("photo_saved") and ph2.button("Remove photo", key="cv_photo_remove"):
            if api.call(api.request, "DELETE", "/cv-photo", success="Photo removed."):
                st.rerun()
        if st.button("Save CV header details"):
            langs = []
            for line in langs_text.splitlines():
                if line.strip():
                    name, _, level = line.partition(" - ")
                    langs.append({"name": name.strip(), "level": level.strip()})
            body = {"contact": {"email": email, "phone": phone, "location": location, "linkedin": linkedin},
                    "languages": langs,
                    "interests": [x.strip() for x in interests_text.splitlines() if x.strip()]}
            if api.call(api.put, "/cv-extras", body, success="Saved. The preview uses these details."):
                st.rerun()

    st.caption("The CV is built from your approved profile. Preview it, edit anything you want, then approve. "
               "Only approved files are created, and your uploaded CV is never modified.")
    versions = api.call(api.get, "/cv-versions") or []
    if not versions:
        st.info("No CV versions yet. Score jobs, then propose CV changes for a group or job.")
    for v in versions:
        target = v.get("group_name") or v.get("job_title") or ""
        pending = sum(p["status"] == "proposed" for p in v["proposals"])
        with st.expander(f"CV version #{v['id']} for {target} - {v['status']}, {pending} pending",
                         expanded=v["status"] != "generated"):
            a1, a2, a3 = st.columns(3)
            if pending and a1.button("Approve all changes", key=f"aa{v['id']}"):
                api.call(api.post, f"/cv-versions/{v['id']}/decide-all", {"approve": True})
                st.rerun()
            if pending and a2.button("Reject all changes", key=f"ra{v['id']}"):
                api.call(api.post, f"/cv-versions/{v['id']}/decide-all", {"approve": False})
                st.rerun()
            if a3.button("Delete version", key=f"dv{v['id']}"):
                api.call(api.delete, f"/cv-versions/{v['id']}")
                st.rerun()

            # Suggested changes from the matching step. They are approved one by one here.
            if v["proposals"]:
                with st.expander(f"Suggested changes ({len(v['proposals'])})"):
                    for p in v["proposals"]:
                        with st.container(border=True):
                            st.markdown(f"**{p['change_type']}** in _{p['section']}_ - **{p['status']}**")
                            if p.get("original_text"):
                                st.markdown(f"Before: {p['original_text']}")
                            if p.get("proposed_text"):
                                st.markdown(f"After: {p['proposed_text']}")
                            st.caption(f"Why: {p.get('reason') or ''} | Evidence: {', '.join(p.get('evidence') or [])}")
                            b1, b2 = st.columns(2)
                            if p["status"] != "approved" and b1.button("Approve", key=f"ap{p['id']}"):
                                api.call(api.post, f"/cv-proposals/{p['id']}/decision", {"approve": True})
                                st.rerun()
                            if p["status"] != "rejected" and b2.button("Reject", key=f"rp{p['id']}"):
                                api.call(api.post, f"/cv-proposals/{p['id']}/decision", {"approve": False})
                                st.rerun()

            # The preview: the same layout as the DOCX and PDF.
            prev = api.call(api.get, f"/cv-versions/{v['id']}/preview") or {}
            if prev:
                if prev.get("has_edits"):
                    st.caption("Showing your saved edits. Reset to automatic to go back to the profile version.")
                components.html(prev["html"], height=1150, scrolling=True)

                # Edit the sections. Tick "Leave out" to drop an entry (for example, to trim the project list).
                with st.expander("Edit sections"):
                    structure = prev.get("structure") or {"sections": []}
                    edited = []
                    for si, s in enumerate(structure.get("sections") or []):
                        st.markdown(f"**{s.get('title')}**")
                        kept = []
                        for ii, it in enumerate(s.get("items") or []):
                            k = f"cv{v['id']}_{si}_{ii}"
                            with st.container(border=True):
                                drop = st.checkbox("Leave out of the CV", key=f"{k}_drop")
                                heading_val = it.get("heading") or ""
                                if len(heading_val) > 90:
                                    heading = st.text_area("Heading", heading_val, key=f"{k}_h", height=110)
                                else:
                                    heading = st.text_input("Heading", heading_val, key=f"{k}_h")
                                sub = st.text_input("Role or detail", it.get("subheading") or "", key=f"{k}_sub")
                                dates = st.text_input("Dates", it.get("dates") or "", key=f"{k}_dates")
                                bullets_val = "\n".join(it.get("bullets") or [])
                                bullets = st.text_area("Bullets (one per line)", bullets_val, key=f"{k}_b",
                                                       height=min(300, 40 + 24 * (bullets_val.count("\n") + 1)))
                            if not drop:
                                kept.append({"heading": heading, "subheading": sub, "dates": dates,
                                             "location": it.get("location") or "",
                                             "bullets": [x.strip() for x in bullets.splitlines() if x.strip()]})
                        if kept:
                            edited.append({"title": s.get("title"), "items": kept})
                    if st.button("Save edits", key=f"sv{v['id']}"):
                        body = {"structure": {"name": structure.get("name"), "headline": structure.get("headline"),
                                              "sections": edited}}
                        if api.call(api.put, f"/cv-versions/{v['id']}/draft", body, success="Edits saved."):
                            st.rerun()
                    if prev.get("has_edits") and st.button("Reset to automatic", key=f"rs{v['id']}"):
                        if api.call(api.delete, f"/cv-versions/{v['id']}/draft"):
                            st.rerun()

            # Approve: creates the DOCX and PDF from the saved preview.
            if pending:
                st.warning(f"{pending} suggested change(s) still need a decision before you can approve.")
            st.caption("Save edits before you approve, so the files match the preview.")
            if st.button("Approve and create DOCX and PDF", key=f"gen{v['id']}", type="primary",
                         disabled=bool(pending)):
                if api.call(api.post, f"/cv-versions/{v['id']}/generate", timeout=api.LONG_TIMEOUT,
                            spinner="Creating the files..."):
                    st.rerun()
            if v["status"] == "generated":
                st.success("Files are ready. Download below. Editing the preview later needs a new approval.")
                d1, d2 = st.columns(2)
                for kind, col in (("docx", d1), ("pdf", d2)):
                    data_file = api.call(api.get, f"/cv-versions/{v['id']}/download/{kind}", timeout=60)
                    if data_file:
                        path = v.get(f"{kind}_path") or f"cv.{kind}"
                        col.download_button(f"Download {kind.upper()}", data_file,
                                            file_name=path.replace("\\", "/").split("/")[-1],
                                            key=f"dl{kind}{v['id']}")
