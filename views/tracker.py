"""Workflow Tracker: every request from arrival to invoice, with its checks, actions and history."""
import pandas as pd
import streamlit as st

from views import common as ui
from workflow import rules, store

conn = ui.workspace()
customers = ui.customers()
now = ui.now()

ui.header("Workflow tracker", "Every billing request by status, with its checks, next action and full history")

reqs = pd.DataFrame(store.all_requests(conn))
counts = reqs["status"].value_counts()
cols = st.columns(len(rules.ALL_STATUSES))
for col, s in zip(cols, rules.ALL_STATUSES):
    ui.status_tile(col, s, int(counts.get(s, 0)))

st.write("")
f1, f2 = st.columns([2, 1])
show = f1.multiselect("Show statuses", rules.ALL_STATUSES, default=rules.OPEN_STATUSES, key="t_status")
search = f2.text_input("Search (ID, customer, work order)", key="t_search")
view = reqs[reqs["status"].isin(show or rules.ALL_STATUSES)].copy()
if search:
    s = search.strip().lower()
    view = view[view[["request_id", "customer_name", "work_order"]].astype(str)
                .apply(lambda c: c.str.lower().str.contains(s, regex=False)).any(axis=1)]
view["next_action"] = [store.next_action(r, now) for r in view.to_dict("records")]
view = view.sort_values("received_at", ascending=False)
table = view[["request_id", "status", "next_action", "customer_name", "total_amount", "billing_category",
              "submitted_by_team", "received_at"]].rename(columns={
    "request_id": "Request", "received_at": "Received", "submitted_by_team": "Team", "customer_name": "Customer",
    "billing_category": "Category", "total_amount": "Amount", "status": "Status", "next_action": "Next action"})
event = st.dataframe(table, hide_index=True, width="stretch", height=360, on_select="rerun", selection_mode="single-row",
                     column_config={"Amount": st.column_config.NumberColumn(format="dollar"),
                                    "Request": st.column_config.TextColumn(width="small"),
                                    "Next action": st.column_config.TextColumn(width="medium")}, key="t_table")
picked = event.selection.rows if event and event.selection else []
options = view["request_id"].tolist()
if picked and picked[0] < len(options) and options[picked[0]] != st.session_state.get("t_last_row"):
    st.session_state["t_last_row"] = options[picked[0]]
    st.session_state["t_open"] = options[picked[0]]  # a clicked row opens that request
if st.session_state.get("t_open") not in [""] + options:
    st.session_state["t_open"] = ""
rid = st.selectbox("Open a request (or click a row above)", [""] + options, key="t_open")
if not rid:
    st.caption("Select a request to see its checks, actions and history.")
    ui.ask_assistant("Workflow Tracker")
    ui.footer()
    st.stop()

req = store.get_request(conn, rid)
findings = store.findings_for(conn, req, customers, now.date())
result = rules.readiness(findings, bool(req.get("approved_by")))

st.divider()
st.subheader(f"{rid} · {req.get('customer_name') or 'no customer name'}")
st.markdown(f"Status {ui.badge(req['status'])} &nbsp; Checks {ui.badge(result)} &nbsp; "
            f"Next action: **{store.next_action(req, now)}**", unsafe_allow_html=True)
if req.get("exception"):
    ui.exception_card("Held at reconciliation", req["exception"])

left, right = st.columns([1, 1])
with left:
    st.markdown("**Checks**")
    if not findings:
        st.markdown(ui.badge("Ready") + " All 16 checks passed.", unsafe_allow_html=True)
    for f in sorted(findings, key=lambda f: rules.SEVERITY_ORDER[f.severity]):
        label = "Needs approval" if f.severity == "Approval" and not req.get("approved_by") else \
            ("Approved" if f.severity == "Approval" else rules.SEVERITY_LABEL[f.severity])
        st.markdown(f"{ui.badge(label)} {ui.esc(f.message)}", unsafe_allow_html=True)
    if req.get("approved_by"):
        st.caption(f"Approved by {req['approved_by']} on {req['approved_at']}.")
    st.markdown("**Details**")
    details = pd.DataFrame([{"Field": rules.FIELD_LABELS[f], "Value": "" if req.get(f) is None else str(req.get(f))}
                            for f in rules.REQUEST_FIELDS if req.get(f) not in (None, "")])
    st.dataframe(details, hide_index=True, width="stretch")

with right:
    st.markdown("**Actions**")
    editable = req["status"] in store.EDITABLE
    if req["status"] == "Needs information":
        subject, body = rules.follow_up_email(req, findings, "Billing Analyst")
        with st.expander("Follow-up email draft", expanded=True):
            st.text_input("Subject", subject, key=f"t_subj_{rid}")
            st.text_area("Email (edit before sending)", body, height=220, key=f"t_body_{rid}")
            st.caption("Draft only. Nothing is sent from this app.")
            if st.button("Mark as sent (simulated)" if not req.get("followups_sent") else "Mark reminder as sent",
                         key=f"t_sent_{rid}"):
                store.record_follow_up(conn, rid, ui.role(), now)
                st.rerun()
    if editable:
        with st.expander("Correct details and run the checks again", expanded=req["status"] == "Needs information"):
            fields_to_edit = list(dict.fromkeys([f.field for f in findings if f.field] +
                                                ["total_amount", "customer_account"]))
            changes = {}
            for f in fields_to_edit:
                cur = req.get(f)
                if f == "supporting_docs":
                    changes[f] = st.selectbox(rules.FIELD_LABELS[f], ["", "Yes", "No"],
                                              index=["", "Yes", "No"].index(cur) if cur in ("Yes", "No") else 0,
                                              key=f"t_e_{rid}_{f}")
                else:
                    changes[f] = st.text_input(rules.FIELD_LABELS[f], "" if cur is None else str(cur),
                                               key=f"t_e_{rid}_{f}", max_chars=200)
            if req.get("approved_by"):
                st.caption("Changing the amount, customer or category clears the existing approval.")
            if st.button("Save and re-check", type="primary", key=f"t_save_{rid}"):
                store.update_request(conn, rid, changes, ui.role(), now, customers)
                st.rerun()
    if req["status"] == "Awaiting approval":
        if ui.role() != store.SUPERVISOR:
            st.info("Approval needs the Supervisor role. Switch the simulated role in the sidebar.",
                    icon=":material/supervisor_account:")
        else:
            try_label = f"Approve ${req['total_amount']:,.2f}"
            if st.button(try_label, type="primary", key=f"t_appr_{rid}"):
                try:
                    store.approve(conn, rid, ui.role(), now, customers)
                    st.rerun()
                except (PermissionError, ValueError) as e:
                    st.error(ui.esc(e))
    if req["status"] == "Ready to bill":
        st.markdown("Ready for the next billing batch on the Billing Quality page.")
        if st.button("Go to Billing Quality", key=f"t_bq_{rid}"):
            st.switch_page("views/quality.py")
    if editable:
        with st.expander("Cancel this request"):
            reason = st.text_input("Reason", key=f"t_cr_{rid}", max_chars=200)
            if st.button("Cancel request", key=f"t_cancel_{rid}", disabled=not reason.strip()):
                store.cancel(conn, rid, ui.role(), now, reason.strip())
                st.rerun()
    if not editable and req["status"] != "In billing batch":
        st.caption(f"No actions: the request is {req['status'].lower()}.")

    st.markdown("**History**")
    hist = store.table(conn, "SELECT ts AS Time, user AS Who, action AS Action, detail AS Detail FROM events "
                             "WHERE request_id = ? ORDER BY id DESC", (rid,))
    st.dataframe(hist, hide_index=True, width="stretch", height=240)

ui.ask_assistant("Workflow Tracker", f"Explain the status of {rid} and what should happen next.",
                 label=f"Ask the assistant about {rid}")
ui.footer()
