import streamlit as st

import api_client as api

st.title("Outreach")
st.caption("Drafts are written for you; you edit, approve and send. Emails go one at a time from your Gmail. "
           "LinkedIn messages you send yourself.")

top1, top2 = st.columns([1, 3])
if top1.button("Check replies"):
    res = api.call(api.post, "/outreach/check-replies", timeout=api.LONG_TIMEOUT, spinner="Reading tracked threads...")
    if res:
        top2.info(f"Checked {res['checked']} threads, {res['new_replies']} new replies. {res.get('message') or ''}")

tab_job, tab_threads = st.tabs(["By job", "All threads"])


def render_thread(t: dict, scope: str = "") -> None:
    contact = t.get("contact") or {}
    job = t.get("job") or {}
    st.markdown(f"**Thread #{t['id']}** - {t['channel']} - **{t['status']}**  \n"
                f"{contact.get('full_name')} ({contact.get('email') or contact.get('linkedin_url') or ''}) "
                f"about #{job.get('id')} {job.get('title')} at {job.get('company')}")
    for m in t["messages"]:
        who = "You" if m["direction"] == "outbound" else contact.get("full_name") or "Them"
        with st.chat_message("user" if m["direction"] == "outbound" else "assistant"):
            st.caption(f"{who} - {m['status']}{' - ' + m['reply_category'] if m.get('reply_category') else ''}")
            if m["status"] in ("draft", "approved", "failed") and m["direction"] == "outbound":
                label = "Connection note" if t["channel"] == "linkedin" else "Subject"
                subj = st.text_input(label, m.get("subject") or "", key=f"{scope}-s{m['id']}")
                body = st.text_area("Message", m["body"], height=220, key=f"{scope}-b{m['id']}")
                if m.get("attachment_paths"):
                    st.caption("Attachment: " + ", ".join(p.replace("\\", "/").split("/")[-1] for p in m["attachment_paths"]))
                c1, c2, c3, c4 = st.columns(4)
                edited = subj != (m.get("subject") or "") or body != m["body"]
                if c1.button("Save edits", key=f"{scope}-e{m['id']}", disabled=not edited):
                    api.call(api.put, f"/outreach/messages/{m['id']}", {"subject": subj, "body": body})
                    st.rerun()
                if t["channel"] == "email":
                    if m["status"] in ("draft", "failed"):
                        if c2.button("Approve", key=f"{scope}-a{m['id']}", disabled=edited,
                                     help="Save edits first" if edited else None):
                            api.call(api.post, f"/outreach/messages/{m['id']}/approve")
                            st.rerun()
                    else:
                        dup = c3.checkbox("Send even if already emailed", key=f"{scope}-dup{m['id']}")
                        if c2.button("Send now", key=f"{scope}-send{m['id']}", type="primary"):
                            if api.call(api.post, f"/outreach/messages/{m['id']}/send", {"confirm_duplicate": dup},
                                        timeout=120, spinner="Sending one email..."):
                                st.success("Sent.")
                                st.rerun()
                    url = api.call(api.get, f"/outreach/messages/{m['id']}/gmail-compose-url")
                    if url:
                        c4.link_button("Open in Gmail instead", url["url"])
                else:
                    if contact.get("linkedin_url"):
                        c2.link_button("Open LinkedIn profile", contact["linkedin_url"])
                    if c3.button("I sent it on LinkedIn", key=f"{scope}-ls{m['id']}"):
                        api.call(api.post, f"/outreach/threads/{t['id']}/status", {"status": "sent"})
                        st.rerun()
                    st.code(body, language=None)
                if c4.button("Discard draft", key=f"{scope}-x{m['id']}"):
                    api.call(api.delete, f"/outreach/messages/{m['id']}")
                    st.rerun()
                if t["channel"] == "email":
                    if m.get("attachment_paths"):
                        st.caption("Attached: " + ", ".join(p.replace("\\", "/").split("/")[-1]
                                                           for p in m["attachment_paths"]))
                    cv_a, cv_b = st.columns(2)
                    if cv_a.button("Attach CV", key=f"{scope}-att{m['id']}",
                                   help="Attach the generated CV for this job or its group"):
                        if api.call(api.post, f"/outreach/messages/{m['id']}/attach-cv", success="CV attached."):
                            st.rerun()
                    if cv_b.button("Create CV for this job", key=f"{scope}-mkcv{m['id']}",
                                   help="Same process as Tailored CVs. Generates and attaches when no changes are pending."):
                        res = api.call(api.post, f"/outreach/messages/{m['id']}/make-cv", timeout=api.LONG_TIMEOUT,
                                       spinner="Preparing the CV...")
                        if res:
                            if res.get("status") == "needs_review":
                                st.info(f"{res['pending']} CV change(s) to review in Matches and CVs > Tailored CVs. "
                                        "Approve them there, then click Attach CV here.")
                            else:
                                st.success("CV created and attached.")
                                st.rerun()
                refine_text = st.text_input("Refine this draft", key=f"{scope}-rf{m['id']}",
                                            placeholder="e.g. shorter, friendlier, mention the SOC project")
                if st.button("Refine draft", key=f"{scope}-rfb{m['id']}", disabled=not refine_text.strip()):
                    if api.call(api.post, f"/outreach/messages/{m['id']}/refine", {"instruction": refine_text},
                                timeout=api.LONG_TIMEOUT, spinner="Rewriting the draft..."):
                        st.rerun()
                st.caption("A refined draft must be approved again before it can be sent.")
            else:
                if m.get("subject"):
                    st.markdown(f"**{m['subject']}**")
                st.write(m["body"])
    has_reply = any(m["direction"] == "inbound" for m in t["messages"])
    if t["channel"] == "linkedin":
        reply = st.text_area("Paste their LinkedIn reply", key=f"{scope}-lr{t['id']}")
        if st.button("Save their reply", key=f"{scope}-slr{t['id']}") and reply.strip():
            api.call(api.post, f"/outreach/threads/{t['id']}/linkedin-reply", {"text": reply})
            st.rerun()
    if has_reply:
        guidance = st.text_input("What do you want to say next? (optional)", key=f"{scope}-gd{t['id']}",
                                 placeholder="e.g. accept the interview, ask for the salary range")
        if st.button("Draft my reply", key=f"{scope}-dr{t['id']}", type="primary"):
            res = api.call(api.post, f"/outreach/threads/{t['id']}/draft-reply", {"guidance": guidance},
                           timeout=api.LONG_TIMEOUT, spinner="Drafting your reply...")
            if res:
                if res.get("notes_for_user"):
                    st.warning(res["notes_for_user"])
                st.rerun()
    s1, s2, _ = st.columns([1, 1, 3])
    if t["status"] not in ("closed",) and s1.button("Close thread", key=f"{scope}-cl{t['id']}"):
        api.call(api.post, f"/outreach/threads/{t['id']}/status", {"status": "closed"})
        st.rerun()
    if t["status"] == "draft" and s2.button("Skip", key=f"{scope}-sk{t['id']}"):
        api.call(api.post, f"/outreach/threads/{t['id']}/status", {"status": "skipped"})
        st.rerun()
    with st.expander("Delete this thread"):
        st.caption("Removes this thread and its messages from the app. Emails already sent stay in your Gmail.")
        confirm = st.checkbox("I want to delete this thread", key=f"{scope}-delc{t['id']}")
        if st.button("Delete thread", key=f"{scope}-del{t['id']}", disabled=not confirm, type="primary"):
            if api.call(api.delete, f"/outreach/threads/{t['id']}", success="Thread deleted."):
                st.rerun()


def render_job_tab() -> None:
    jobs = (api.call(api.get, "/jobs", params={"limit": 500}) or {}).get("items") or []
    jobs = [j for j in jobs if j["status"] not in ("rejected", "archived")]
    if not jobs:
        st.info("No jobs yet.")
        return
    job_id = st.selectbox("Job", [j["id"] for j in jobs], format_func=lambda i: next(
        f"#{j['id']} {j['title']} - {j['company']}" for j in jobs if j["id"] == i))
    card = api.call(api.get, f"/jobs/{job_id}/outreach")
    if not card:
        return
    job = card["job"]
    h1, h2 = st.columns([3, 1])
    cv = card.get("cv_version")
    h1.markdown(f"**{job['title']}** at {job['company']}  \nCV to attach: "
                + (f"version #{cv['id']}" if cv else "_none generated yet (Matches and CVs page)_"))
    if job.get("apply_url"):
        h2.link_button("Open apply link", job["apply_url"])

    st.subheader("Contacts")
    if card["message"]:
        st.info(card["message"])
    for c in card["contacts"]:
        ct = c["contact"]
        with st.container(border=True):
            st.markdown(f"**{ct['full_name']}** - {ct.get('title') or ''} ({ct['source']}, {ct.get('role')})  \n"
                        f"Email: {ct.get('email') or 'unknown'} ({ct.get('email_status')}) | "
                        f"LinkedIn: {ct.get('linkedin_url') or 'unknown'}  \nRecommended: **{c['recommended']}**")
            k1, k2, k3, k4 = st.columns(4)
            if ct.get("email") and k1.button("Draft email", key=f"de{ct['id']}"):
                api.call(api.post, "/outreach/drafts", {"job_id": job_id, "contact_id": ct["id"], "channel": "email",
                                                        "cv_version_id": cv["id"] if cv else None},
                         timeout=api.LONG_TIMEOUT, spinner="Drafting...")
                st.rerun()
            if ct.get("linkedin_url") and k2.button("Draft LinkedIn message", key=f"dli{ct['id']}"):
                api.call(api.post, "/outreach/drafts", {"job_id": job_id, "contact_id": ct["id"], "channel": "linkedin",
                                                        "cv_version_id": cv["id"] if cv else None},
                         timeout=api.LONG_TIMEOUT, spinner="Drafting...")
                st.rerun()
            if ct["source"] == "apollo" and not ct.get("email") and k3.button(
                    "Reveal email (spends Apollo credits)", key=f"rv{ct['id']}"):
                api.call(api.post, f"/contacts/{ct['id']}/reveal-email", timeout=60)
                st.rerun()
            if k4.button("Remove", key=f"rm{ct['id']}"):
                api.call(api.delete, f"/jobs/{job_id}/contacts/{ct['id']}")
                st.rerun()

    with st.expander("Find or add a contact"):
        f1, f2 = st.columns(2)
        if f1.button("Use emails written in the posting"):
            res = api.call(api.post, f"/jobs/{job_id}/contacts/from-posting")
            if res:
                st.rerun()
            elif res is not None:
                st.info("No email addresses are written in this posting.")
        if f2.button("Search Apollo (no email reveal)"):
            res = api.call(api.post, f"/jobs/{job_id}/contacts/apollo-search", {"titles": []}, timeout=60,
                           spinner="Searching Apollo...")
            if res:
                st.session_state[f"apollo_{job_id}"] = res["people"]
        for i, p in enumerate(st.session_state.get(f"apollo_{job_id}") or []):
            p1, p2 = st.columns([5, 1])
            p1.write(f"{p['full_name']} - {p.get('title')} - {p.get('company')} {p.get('linkedin_url') or ''}")
            if p2.button("Save", key=f"ap{job_id}_{i}"):
                api.call(api.post, f"/jobs/{job_id}/contacts/apollo-save", p)
                st.rerun()
        with st.form(f"manual{job_id}", clear_on_submit=True):
            m1, m2 = st.columns(2)
            name = m1.text_input("Name")
            title = m2.text_input("Title")
            email = m1.text_input("Email")
            li = m2.text_input("LinkedIn URL")
            role = m1.selectbox("Role", ["recruiter", "hiring_manager", "careers_inbox", "other"])
            if st.form_submit_button("Add contact") and name:
                api.call(api.post, f"/jobs/{job_id}/contacts", {"full_name": name, "title": title, "email": email,
                                                                 "linkedin_url": li, "role": role,
                                                                 "company": job.get("company") or ""})
                st.rerun()

    st.subheader("Threads for this job")
    if not card["threads"]:
        st.caption("No outreach yet.")
    for t in card["threads"]:
        kind = "LinkedIn" if t["channel"] == "linkedin" else "Email"
        contact_name = (t.get("contact") or {}).get("full_name") or "no contact"
        with st.expander(f"#{t['id']} {kind} - {t['status']} - {contact_name}"):
            render_thread(api.call(api.get, f"/outreach/threads/{t['id']}") or t, "job")


with tab_job:
    render_job_tab()

with tab_threads:
    f1, f2 = st.columns(2)
    channel = f1.selectbox("Channel", ["", "linkedin", "email"], format_func=lambda x: {"": "All", "linkedin": "LinkedIn",
                                                                                         "email": "Email"}[x],
                           key="thread_channel")
    status = f2.selectbox("Status", ["", "draft", "waiting", "replied", "closed", "skipped"],
                          format_func=lambda x: x or "any", key="thread_status")
    threads = api.call(api.get, "/outreach/threads", params={"status": status} if status else None) or []
    if channel:
        threads = [t for t in threads if t["channel"] == channel]
    st.caption(f"{len(threads)} thread(s). Open one to read it, reply, or change its status.")
    for t in threads:
        contact = t.get("contact") or {}
        job = t.get("job") or {}
        kind = "LinkedIn" if t["channel"] == "linkedin" else "Email"
        label = (f"#{t['id']} {kind} - {t['status']} - {contact.get('full_name') or 'no contact'} - "
                 f"{job.get('title') or 'no job'} at {job.get('company') or '-'}")
        with st.expander(label):
            full = api.call(api.get, f"/outreach/threads/{t['id']}") or t
            manage = ["waiting", "replied", "closed", "skipped"]
            options = manage if t["status"] in manage else [t["status"]] + manage
            m1, m2 = st.columns([3, 1])
            new_status = m1.selectbox("Status", options, index=options.index(t["status"]), key=f"ts{t['id']}")
            if m2.button("Update status", key=f"tsb{t['id']}", disabled=new_status == t["status"]):
                if api.call(api.post, f"/outreach/threads/{t['id']}/status", {"status": new_status},
                            success="Status updated."):
                    st.rerun()
            render_thread(full, "all")
