"""Guided demo: three scenarios that run the real checks, approvals and reconciliation."""
import pandas as pd
import streamlit as st

from ai import context as ai_context
from ai.providers import AIError
from views import common as ui
from workflow import exports, rules, scenarios, store

conn = ui.workspace()
customers = ui.customers()
demo = st.session_state.setdefault("demo", {})

ui.header("Guided demo", "Three short scenarios, about two minutes in total. Every step runs the real logic "
                         "on your own copy of the demo data.")


def findings_list(findings, show_ok=True):
    if not findings and show_ok:
        st.markdown(ui.badge("Ready") + " All 16 checks passed.", unsafe_allow_html=True)
    for f in sorted(findings, key=lambda f: rules.SEVERITY_ORDER[f.severity]):
        st.markdown(f"{ui.badge(rules.SEVERITY_LABEL[f.severity])} {ui.esc(f.message)}", unsafe_allow_html=True)


def status_line(rid):
    req = store.get_request(conn, rid)
    st.markdown(f"**{rid}** is now {ui.badge(req['status'])}", unsafe_allow_html=True)
    return req


steps_done = sum(bool(demo.get(k)) for k in ("a", "b_logged", "b_draft", "b_fixed", "b_approved", "c_batch",
                                             "c_recon", "c_resolved"))
st.progress(steps_done / 8, text=f"{steps_done} of 8 steps done")

# ---------------------------------------------------------------- A
with st.container(border=True):
    st.subheader("A. A complete request")
    st.markdown("<div class='panel-note'>A request arrives by email with everything filled in.</div>",
                unsafe_allow_html=True)
    if not demo.get("a"):
        text = scenarios.email_a(conn, ui.now().date())
        with st.expander("The email", expanded=True):
            st.code(text, language=None, wrap_lines=True)
        if st.button("Log and check this request", type="primary", key="a_go"):
            demo["a"] = scenarios.log_email(conn, text, ui.role(), ui.now(), customers)["request_id"]
            st.rerun()
    else:
        rid = demo["a"]
        status_line(rid)
        findings_list(store.findings_for(conn, store.get_request(conn, rid), customers, ui.now().date()))
        st.caption("No one had to retype or check it by hand. It will go in the next billing batch.")

# ---------------------------------------------------------------- B
with st.container(border=True):
    st.subheader("B. Missing information")
    st.markdown(f"<div class='panel-note'>A damage recovery request for {scenarios.B_CUSTOMER}, over the "
                f"illustrative ${rules.APPROVAL_LIMIT:,.0f} approval limit, arrives without its claim number or "
                "documents.</div>", unsafe_allow_html=True)
    if not demo.get("b_logged"):
        text = scenarios.email_b(conn, ui.now().date())
        with st.expander("The email", expanded=bool(demo.get("a"))):
            st.code(text, language=None, wrap_lines=True)
        if st.button("Log and check this request", type="primary", key="b_go"):
            demo["b_logged"] = scenarios.log_email(conn, text, ui.role(), ui.now(), customers)["request_id"]
            st.rerun()
    else:
        rid = demo["b_logged"]
        req = store.get_request(conn, rid)
        findings = store.findings_for(conn, req, customers, ui.now().date())

        st.markdown("**1. Checked on arrival**")
        if not demo.get("b_fixed"):
            status_line(rid)
            findings_list(findings)

        st.markdown("**2. Follow-up drafted**")
        if not demo.get("b_draft"):
            if st.button("Draft the follow-up email", key="b_draft_go", type="primary"):
                first = store.findings_for(conn, req, customers, ui.now().date())
                demo["b_draft"] = rules.follow_up_email(req, first, "Billing Analyst")
                st.rerun()
        else:
            subject, body = demo["b_draft"]
            st.text_input("Subject", subject, key="b_subj")
            st.text_area("Email (edit before sending)", body, height=230, key="b_body")
            st.caption("Written from the failed checks, so it asks for exactly what is missing. Nothing is sent "
                       "from this app; an analyst reviews it and sends it from their own email.")
            if not req.get("followups_sent"):
                if st.button("Mark as sent (simulated)", key="b_sent"):
                    store.record_follow_up(conn, rid, ui.role(), ui.now())
                    st.rerun()

        if demo.get("b_draft"):
            st.markdown("**3. The requester replies. Add the details and check again**")
            if not demo.get("b_fixed"):
                with st.expander("The reply", expanded=True):
                    st.code(scenarios.reply_b(rid), language=None, wrap_lines=True)
                c1, c2 = st.columns([1, 1])
                c1.text_input("Claim or police report number", key="b_claim",
                              placeholder="Type the number from the reply")
                c2.checkbox("Supporting documents received", key="b_docs")

                def recheck():
                    new = scenarios.correct_b(conn, rid, st.session_state.get("b_claim", ""),
                                              st.session_state.get("b_docs", False), ui.role(), ui.now(), customers)
                    demo["b_recheck"] = new
                    demo["b_fixed"] = not any(f.severity == "Blocker" for f in new)

                st.button("Run the checks again", type="primary", key="b_fix", on_click=recheck)
                if demo.get("b_recheck"):
                    st.warning("Still on hold. The checks say:")
                    findings_list(demo["b_recheck"])
            else:
                st.markdown(f"{ui.badge('Ready')} Claim number and documents added. The checks ran again and nothing "
                            "is missing. Only the approval is left.", unsafe_allow_html=True)

        if demo.get("b_fixed"):
            st.markdown("**4. Supervisor approval**")
            req = store.get_request(conn, rid)
            if demo.get("b_approved"):
                st.markdown(f"Approved by {req['approved_by'] or 'Supervisor'}. {ui.badge('Ready to bill')}",
                            unsafe_allow_html=True)
                st.caption("If the amount, customer or category changes now, the approval is cleared automatically.")
            elif req["status"] == "Awaiting approval":
                st.markdown(f"At \\${req['total_amount']:,.2f} it is over the limit, so a supervisor who did not log "
                            "it must approve it.")
                if ui.role() != store.SUPERVISOR:
                    st.button("Switch to Supervisor (simulated role)", key="b_role",
                              on_click=lambda: st.session_state.update(role=store.SUPERVISOR))
                elif st.button("Approve as Supervisor", type="primary", key="b_approve"):
                    store.approve(conn, rid, ui.role(), ui.now(), customers)
                    demo["b_approved"] = True
                    st.rerun()
            elif req["status"] == "Ready to bill":
                demo["b_approved"] = True
                st.rerun()
            else:
                status_line(rid)

# ---------------------------------------------------------------- C
with st.container(border=True):
    st.subheader("C. A billing mismatch")
    st.markdown("<div class='panel-note'>Ready requests go to billing in one file. When the invoices come back, each "
                "one is matched to its request before anything is marked billed.</div>", unsafe_allow_html=True)
    if not (demo.get("a") and demo.get("b_approved")):
        st.caption("Finish A and B first, so their requests are in this batch.")
    elif not demo.get("c_batch"):
        ready = store.table(conn, "SELECT request_id, total_amount FROM requests WHERE status = 'Ready to bill'")
        st.markdown(f"{len(ready)} requests are ready, including the two from A and B.")
        if st.button("Send ready requests to billing", type="primary", key="c_go"):
            demo["c_batch"] = scenarios.send_batch(conn, ui.role(), ui.now())
            st.rerun()
    else:
        batch = demo["c_batch"]
        st.markdown(f"**1. Billing file created:** batch {batch['batch_id']}, {batch['count']} requests, "
                    f"control total ${batch['control_total']:,.2f}.")
        st.download_button("Download the billing file (CSV)", exports.to_csv_bytes(batch["upload"]),
                            f"{batch['batch_id']}.csv", "text/csv", key="c_dl")

        st.markdown("**2. Invoices come back from the billing system**")
        if not demo.get("c_recon"):
            if st.button("Load the sample confirmation and reconcile", type="primary", key="c_recon_go"):
                conf = scenarios.sample_confirmation(batch["upload"], demo.get("b_logged"))
                demo["c_recon"] = scenarios.reconcile(conn, batch["batch_id"], conf, ui.role(), ui.now())
                st.rerun()
        else:
            res = demo["c_recon"]
            counts = res["counts"]
            st.markdown(f"{counts.get('Matched', 0)} matched and marked billed. "
                        f"{len(res['held'])} held: {ui.badge('Amount differs')}", unsafe_allow_html=True)
            if res.get("target"):
                ui.exception_card(
                    f"{res['target']}: caught before billing",
                    f"Request ${res['requested']:,.2f} · invoice {res['invoice_number']} ${res['invoiced']:,.2f} · "
                    f"difference {'-' if res['invoiced'] < res['requested'] else '+'}"
                    f"${abs(res['invoiced'] - res['requested']):,.2f}. It stays In billing batch, not Billed.")

            st.markdown("**3. Ask the assistant to explain**")
            provider = ui.ai_provider()
            rule_text = (
                f"The billing system invoiced {res['target']} for ${res['invoiced']:,.2f}, but the request was "
                f"for ${res['requested']:,.2f}. The two amounts use the same digits in a different order, which "
                "usually means a keying error. Because they do not match, the request is held instead of being "
                "marked billed. Next step: ask the billing system team to reissue the invoice for the requested "
                "amount, then record the corrected invoice.")
            if demo.get("c_explained"):
                st.caption(demo.get("c_explained_by", "AI explanation, based only on the app's calculated figures"))
                st.markdown(ui.esc(demo["c_explained"]))
            elif provider is None:
                st.caption("Explanation from the reconciliation rule:")
                st.markdown(ui.esc(rule_text))
            elif st.button("Explain this exception", key="c_explain", icon=":material/forum:"):
                q = ai_context.explain_exception_question(res["target"])
                system = ai_context.system_prompt(ui.metrics(), conn, customers, ui.now(), "Billing Quality")
                with st.container(border=True):
                    try:
                        with st.spinner("Reading the reconciliation..."):
                            text = ui.ai_answer(system, [{"role": "user", "content": q}])
                        st.caption("AI explanation, based only on the app's calculated figures")
                        st.write_stream(ui.type_out(text))
                        demo["c_explained_by"] = "AI explanation, based only on the app's calculated figures"
                    except AIError:
                        text = rule_text
                        demo["c_explained_by"] = "Explanation from the reconciliation rule (the AI is busy right now):"
                        st.caption(demo["c_explained_by"])
                        st.markdown(ui.esc(text))
                demo["c_explained"] = text

            st.markdown("**4. Record the corrected invoice**")
            if not demo.get("c_resolved"):
                if st.button("Record corrected invoice from billing system", type="primary", key="c_fix"):
                    demo["c_resolved"] = scenarios.record_corrected_invoice(conn, res, ui.role(), ui.now())
                    st.rerun()
            else:
                st.markdown(f"Corrected invoice {demo['c_resolved']} matches ${res['requested']:,.2f}. "
                            f"{ui.badge('Billed')}", unsafe_allow_html=True)
                st.success("Done. All three scenarios used the same checks, approvals and reconciliation as the rest "
                           "of the app.", icon=":material/check_circle:")
                rid = demo["b_logged"]
                hist = store.table(conn, "SELECT ts AS Time, user AS Who, action AS Action, detail AS Detail "
                                         "FROM events WHERE request_id = ? ORDER BY id", (rid,))
                with st.expander(f"Full history of {rid}", expanded=True):
                    st.dataframe(hist, hide_index=True, width="stretch")

c1, c2, _ = st.columns([1.3, 1.1, 2.6])
if c1.button("Open the Workflow Tracker", icon=":material/view_kanban:"):
    st.switch_page("views/tracker.py")
if c2.button("Run the demo again", icon=":material/replay:"):
    st.session_state.pop("demo", None)
    st.rerun()
ui.footer()
