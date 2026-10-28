import json

import streamlit as st

import api_client as api

st.title("Profile inputs")
st.caption("Everything the agent knows about you comes from these inputs. Notes override the CV.")

tab_cv, tab_li, tab_gh, tab_proj, tab_profile = st.tabs(
    ["CV and notes", "LinkedIn", "GitHub", "Manual projects", "Built profile"])

# ── CV and notes ───────────────────────────────────────────────────────────────
with tab_cv:
    with st.form("cv_upload", clear_on_submit=True):
        file = st.file_uploader("CV (PDF or DOCX, up to 10 MB)", type=["pdf", "docx"])
        note = st.text_area("Notes about this CV (optional)",
                            placeholder="e.g. I want backend roles, not DevOps. Since 2025 I also use Kafka.")
        if st.form_submit_button("Upload CV", type="primary") and file:
            res = api.call(api.request, "POST", "/cvs", files={"file": (file.name, file.getvalue())},
                           data={"note": note}, timeout=120, spinner="Reading the CV...")
            if res:
                st.success("Already uploaded; note added." if res.get("duplicate") else f"Uploaded {res['file_name']}.")
                if res.get("warning"):
                    st.warning(res["warning"])

    cvs = api.call(api.get, "/cvs") or []
    if not cvs:
        st.info("No CV uploaded yet.")
    for cv in cvs:
        label = f"{'Primary: ' if cv['is_primary'] else ''}{cv['file_name']} ({cv['text_chars']} characters)"
        with st.expander(label, expanded=cv["is_primary"]):
            c1, c2 = st.columns(2)
            if not cv["is_primary"] and c1.button("Make primary", key=f"prim{cv['id']}"):
                api.call(api.post, f"/cvs/{cv['id']}/primary", success="Primary CV changed.")
                st.rerun()
            if c2.button("Delete CV", key=f"del{cv['id']}"):
                api.call(api.delete, f"/cvs/{cv['id']}")
                st.rerun()
            st.markdown("**Notes**")
            for n in cv["notes"]:
                n1, n2 = st.columns([6, 1])
                n1.write(n["note"])
                if n2.button("Delete", key=f"dn{n['id']}"):
                    api.call(api.delete, f"/cv-notes/{n['id']}")
                    st.rerun()
            new_note = st.text_input("Add a note", key=f"note{cv['id']}")
            if st.button("Save note", key=f"sn{cv['id']}") and new_note.strip():
                api.call(api.post, f"/cvs/{cv['id']}/notes", {"note": new_note})
                st.rerun()

# ── LinkedIn ───────────────────────────────────────────────────────────────────
with tab_li:
    st.markdown("Use any of the three options. Only your own profile is read.")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Apify (your public profile)**")
        url = st.text_input("Your LinkedIn profile URL", placeholder="https://www.linkedin.com/in/your-name",
                            help="Leave empty to use LINKEDIN_PROFILE_URL from .env")
        if st.button("Fetch with Apify"):
            if api.call(api.post, "/linkedin/apify", {"profile_url": url}, timeout=330,
                        spinner="Running the Apify actor (can take a few minutes)..."):
                st.success("LinkedIn profile saved.")
    with c2:
        st.markdown("**LinkedIn data export**")
        export = st.file_uploader("Export .zip or a .csv from it", type=["zip", "csv"], key="li_export",
                                  help="LinkedIn: Settings > Data privacy > Get a copy of your data")
        if st.button("Upload export") and export:
            if api.call(api.request, "POST", "/linkedin/export", files={"file": (export.name, export.getvalue())},
                        timeout=120):
                st.success("Export saved.")
    with c3:
        st.markdown("**Saved profile PDF**")
        pdf = st.file_uploader("LinkedIn profile PDF", type=["pdf"], key="li_pdf",
                               help="On your profile: More > Save to PDF")
        if st.button("Upload PDF") and pdf:
            if api.call(api.request, "POST", "/linkedin/pdf", files={"file": (pdf.name, pdf.getvalue())}, timeout=120):
                st.success("PDF saved.")
    sources = api.call(api.get, "/linkedin") or []
    for s in sources:
        s1, s2 = st.columns([6, 1])
        s1.write(f"#{s['id']} {s['source_type']} - {s['fetched_at']} - {s.get('summary')}")
        if s2.button("Delete", key=f"dl{s['id']}"):
            api.call(api.delete, f"/linkedin/{s['id']}")
            st.rerun()

# ── GitHub ─────────────────────────────────────────────────────────────────────
with tab_gh:
    st.markdown(
        "Sync both accounts, then tick the repos you **actually worked on**. Personal repos start ticked "
        "(except forks and repos with 0 commits by you). Company repos start unticked. "
        "For a company repo, **Content allowed** lets the README be read; leave it off to share the name only.")
    g1, g2 = st.columns(2)
    if g1.button("Sync personal GitHub"):
        res = api.call(api.post, "/github/personal/sync", timeout=300, spinner="Listing repos and counting commits...")
        if res:
            st.success(f"{res['total']} repos, {res['added']} new.")
    if g2.button("Sync office GitHub"):
        res = api.call(api.post, "/github/company/sync", timeout=300, spinner="Listing repos and counting commits...")
        if res:
            st.success(f"{res['total']} repos, {res['added']} new.")

    repos = api.call(api.get, "/github/repos") or []
    for account_type, label in (("personal", "Personal repos"), ("company", "Office repos")):
        items = [r for r in repos if r["account_type"] == account_type]
        if not items:
            continue
        st.subheader(f"{label} ({sum(r['is_selected'] for r in items)} of {len(items)} selected)")
        b1, b2, _ = st.columns([1, 1, 4])
        if b1.button("Select all", key=f"sa{account_type}"):
            api.call(api.post, "/github/repos/bulk", {"repo_ids": [r["id"] for r in items], "is_selected": True})
            st.rerun()
        if b2.button("Clear all", key=f"ca{account_type}"):
            api.call(api.post, "/github/repos/bulk", {"repo_ids": [r["id"] for r in items], "is_selected": False})
            st.rerun()
        rows = [{"id": r["id"], "Use": r["is_selected"], "Content allowed": bool(r["llm_allowed"]),
                 "Repo": r["full_name"], "My commits": r["my_commit_count"], "Language": r["primary_language"],
                 "Private": r["is_private"], "Last push": str(r["last_pushed_at"] or "")[:10]} for r in items]
        disabled = ["id", "Repo", "My commits", "Language", "Private", "Last push"]
        if account_type == "personal":
            disabled.append("Content allowed")
        edited = st.data_editor(rows, key=f"ed{account_type}", hide_index=True, width="stretch",
                                disabled=disabled, column_config={"id": None})
        if st.button("Save selection", key=f"save{account_type}", type="primary"):
            changed = 0
            for old, new in zip(rows, edited):
                if old["Use"] != new["Use"] or old["Content allowed"] != new["Content allowed"]:
                    body = {"is_selected": new["Use"]}
                    if account_type == "company":
                        body["llm_allowed"] = new["Content allowed"]
                    api.call(api.patch, f"/github/repos/{old['id']}", body)
                    changed += 1
            st.success(f"Saved {changed} change(s).")
        zero = [r["full_name"] for r in items if r["is_selected"] and r["my_commit_count"] == 0]
        if zero:
            st.warning("Selected with 0 commits by you: " + ", ".join(zero))

# ── Manual projects ────────────────────────────────────────────────────────────
with tab_proj:
    with st.form("project", clear_on_submit=True):
        title = st.text_input("Project name")
        desc = st.text_area("What you built and your part in it")
        tech = st.text_input("Technologies (comma separated)")
        link = st.text_input("Link (optional)")
        if st.form_submit_button("Add project", type="primary"):
            if api.call(api.post, "/projects", {"title": title, "description": desc, "url": link,
                                                "tech": [t.strip() for t in tech.split(",") if t.strip()]}):
                st.success("Project added.")
    for p in api.call(api.get, "/projects") or []:
        p1, p2 = st.columns([6, 1])
        p1.markdown(f"**{p['title']}** - {p['description']}  \n_{', '.join(p.get('tech') or [])}_")
        if p2.button("Delete", key=f"dp{p['id']}"):
            api.call(api.delete, f"/projects/{p['id']}")
            st.rerun()

# ── Built profile ──────────────────────────────────────────────────────────────
with tab_profile:
    if st.button("Build profile", type="primary"):
        if api.call(api.post, "/profile/build", timeout=api.LONG_TIMEOUT,
                    spinner="Reading CV, notes, LinkedIn, GitHub and projects..."):
            st.success("Profile built.")
    current = api.call(api.get, "/profile") or {}
    if not current:
        st.info("No profile yet. Add your inputs, then click Build profile.")
    else:
        prof = current["profile"]
        st.caption(f"Version {current['version']}, built {current['created_at']}")
        st.markdown(f"### {prof.get('full_name') or ''}\n{prof.get('headline') or ''}\n\n{prof.get('summary') or ''}")
        c1, c2 = st.columns(2)
        c1.markdown("**Skills**\n\n" + ", ".join(prof.get("skills") or []))
        c2.markdown("**Preferences**\n\n" + "\n".join(f"- {x}" for x in prof.get("preferences") or []))
        if prof.get("open_questions"):
            st.warning("Questions to answer (add them as CV notes, then rebuild):\n\n"
                       + "\n".join(f"- {q}" for q in prof["open_questions"]))
        with st.expander("Edit profile JSON"):
            text = st.text_area("Profile JSON", json.dumps(prof, indent=2, ensure_ascii=False), height=400)
            if st.button("Save edits"):
                try:
                    api.call(api.put, "/profile", {"profile": json.loads(text)}, success="Saved.")
                except json.JSONDecodeError as exc:
                    st.error(f"Not valid JSON: {exc}")

        # Chat: tell the assistant what to change. Changes are saved as a new version; undo goes back one.
        st.divider()
        st.subheader("Change this profile with the assistant")
        st.caption("Say what to add, remove or correct, or ask a question. Only facts you give, or facts already "
                   "in the profile, are used. Each change is saved as a new version, and you can undo it.")
        history = st.session_state.setdefault("profile_chat", [])
        for entry in history[-12:]:
            with st.chat_message(entry["role"]):
                st.markdown(entry["text"])
                for change in entry.get("changes") or []:
                    st.caption(f"- {change}")
        with st.form("profile_chat_form", clear_on_submit=True):
            instruction = st.text_area("Your instruction", placeholder=(
                "e.g. Add the AWS Agentic AI showcase win as a project. Remove the 2019 internship. "
                "What are my strongest skills for backend roles?"))
            save_note = st.checkbox("Also save this as a CV note, so a rebuild keeps it", value=True)
            sent = st.form_submit_button("Send", type="primary")
        if sent and instruction.strip():
            res = api.call(api.post, "/profile/chat", {"message": instruction, "save_as_note": save_note},
                           timeout=api.LONG_TIMEOUT, spinner="Reading your instruction and the profile...")
            if res:
                history.append({"role": "user", "text": instruction})
                reply = res["reply"] or "Done."
                if res["saved"]:
                    reply += f"\n\nSaved as version {res['version']} (was {res['from_version']})."
                    if res.get("note_saved"):
                        reply += " Also saved as a CV note."
                history.append({"role": "assistant", "text": reply, "changes": res["changes"]})
                st.rerun()
        b1, b2 = st.columns([1, 1])
        if any(e.get("changes") for e in history) and b1.button("Undo last change"):
            if api.call(api.post, "/profile/undo", success="Went back to the previous version."):
                st.rerun()
        if history and b2.button("Clear chat", help="Empties this chat on screen. Saved profile versions are kept."):
            st.session_state["profile_chat"] = []
            st.rerun()
