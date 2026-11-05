"""Billing Quality: batch, export, confirmation and reconciliation. A person reviews before anything is billed."""
import pandas as pd
import streamlit as st

from views import common as ui
from workflow import exports, scenarios, store

conn = ui.workspace()
now = ui.now()

ui.header("Billing quality", "Send checked requests to billing with a control total, then match every invoice back "
                             "to its request before marking it billed")

ready = store.table(conn, "SELECT request_id, customer_name, billing_category, total_amount, approved_by "
                          "FROM requests WHERE status = 'Ready to bill' ORDER BY request_id")

st.subheader("1. Ready to bill")
if ready.empty:
    st.caption("Nothing is ready to bill right now.")
else:
    c = st.columns(3)
    ui.kpi(c[0], "Requests ready", f"{len(ready)}")
    ui.kpi(c[1], "Control total", f"${ready['total_amount'].sum():,.2f}", "Sum of the amounts in the batch")
    ui.kpi(c[2], "Approved over limit", f"{ready['approved_by'].notna().sum()}", "Supervisor approval recorded")
    st.dataframe(ready.rename(columns={"request_id": "Request", "customer_name": "Customer",
                                       "billing_category": "Category", "total_amount": "Amount",
                                       "approved_by": "Approved by"}),
                 hide_index=True, width="stretch", column_config={"Amount": st.column_config.NumberColumn(format="dollar")})
    if st.button("Create billing batch", type="primary", icon=":material/upload_file:"):
        res = scenarios.send_batch(conn, ui.role(), now)
        st.session_state["q_batch"] = res["batch_id"]
        st.rerun()

st.subheader("2. Batches")
batches = store.table(conn, "SELECT batch_id, created_at, created_by, request_count, control_total, status "
                            "FROM batches ORDER BY created_at DESC")
if batches.empty:
    st.caption("No batches yet.")
    ui.footer()
    st.stop()
st.dataframe(batches.rename(columns={"batch_id": "Batch", "created_at": "Created", "created_by": "By",
                                     "request_count": "Requests", "control_total": "Control total", "status": "Status"}),
             hide_index=True, width="stretch", column_config={"Control total": st.column_config.NumberColumn(format="dollar")})

open_batches = batches[batches["status"] != "Confirmed"]["batch_id"].tolist()
all_batches = batches["batch_id"].tolist()
default = st.session_state.get("q_batch")
batch_id = st.selectbox("Batch", all_batches, index=all_batches.index(default) if default in all_batches else 0,
                        key="q_pick")
upload = store.batch_file(conn, batch_id)
row = batches.set_index("batch_id").loc[batch_id]
st.markdown(ui.esc(f"**{batch_id}**: {int(row.request_count)} requests, control total ${row.control_total:,.2f}, "
                   f"file total ${upload['Amount'].sum():,.2f} "
                   + ("(matches)" if abs(upload['Amount'].sum() - row.control_total) < 0.01 else "(DOES NOT MATCH)")))
d1, d2, _ = st.columns([1, 1, 3])
d1.download_button("Billing file (CSV)", exports.to_csv_bytes(upload), f"{batch_id}.csv", "text/csv", key="q_csv")
d2.download_button("Billing file (Excel)", exports.to_excel_bytes(upload, "Upload"), f"{batch_id}.xlsx", key="q_xlsx")
st.caption("Illustrative upload layout; no billing system is connected. Exports are safe to open in Excel.")

st.subheader("3. Reconcile with the billing system")
if batch_id not in open_batches and not store.table(
        conn, "SELECT 1 FROM requests WHERE batch_id = ? AND exception IS NOT NULL", (batch_id,)).shape[0]:
    st.markdown(ui.badge("Matched") + " This batch is fully reconciled.", unsafe_allow_html=True)
else:
    waiting = store.table(conn, "SELECT COUNT(*) AS n FROM requests WHERE batch_id = ? AND status = 'In billing batch' "
                                "AND exception IS NULL", (batch_id,))["n"].iloc[0]
    if waiting:
        st.markdown("Load the billing system's confirmation file (Reference, Invoice Number, Invoice Amount). "
                    "Nothing is marked billed until you review the match and confirm it.")
        c1, c2 = st.columns([1, 2])
        if c1.button("Use a sample confirmation", key="q_sample"):
            st.session_state[f"q_conf_{batch_id}"] = scenarios.sample_confirmation(upload, None)
        file = c2.file_uploader("Confirmation file", type=["csv", "xlsx"], key=f"q_up_{batch_id}",
                                label_visibility="collapsed")
        if file is not None:
            try:
                st.session_state[f"q_conf_{batch_id}"] = exports.read_upload(file.name, file.getvalue())
            except exports.UploadError as e:
                st.error(ui.esc(e))
        conf = st.session_state.get(f"q_conf_{batch_id}")
        if conf is not None:
            try:
                recon = store.reconcile(conn, batch_id, conf)
            except ValueError as e:
                st.error(ui.esc(e))
                recon = None
            if recon is not None:
                show = recon[["request_id", "total_amount", "invoice_number", "invoice_amount", "difference", "result"]]
                st.dataframe(show.rename(columns={"request_id": "Request", "total_amount": "Requested",
                                                  "invoice_number": "Invoice", "invoice_amount": "Invoiced",
                                                  "difference": "Difference", "result": "Result"}),
                             hide_index=True, width="stretch",
                             column_config={c: st.column_config.NumberColumn(format="dollar")
                                            for c in ["Requested", "Invoiced", "Difference"]})
                counts = recon["result"].value_counts()
                st.markdown(" ".join(f"{ui.badge(k)} {v}" for k, v in counts.items()), unsafe_allow_html=True)
                if st.button("Confirm: mark matched invoices as billed and hold the rest", type="primary",
                             key=f"q_confirm_{batch_id}"):
                    store.confirm_batch(conn, batch_id, recon, ui.role(), now)
                    st.session_state.pop(f"q_conf_{batch_id}", None)
                    st.rerun()

    held = store.table(conn, "SELECT request_id, total_amount, exception FROM requests WHERE batch_id = ? "
                             "AND exception IS NOT NULL", (batch_id,))
    for r in held.itertuples():
        with st.container(border=True):
            kind = "No invoice found" if str(r.exception).startswith("No invoice") else "Amount differs"
            st.markdown(f"{ui.badge(kind)} **{r.request_id}**: {ui.esc(r.exception)}",
                        unsafe_allow_html=True)
            c1, c2, c3 = st.columns([1, 1, 1])
            inv_no = c1.text_input("Corrected invoice number", key=f"q_inv_{r.request_id}", max_chars=20)
            amt = c2.number_input("Corrected invoice amount", value=None, min_value=0.0, step=0.01, format="%.2f",
                                  key=f"q_amt_{r.request_id}")
            c3.write("")
            if c3.button("Record corrected invoice", key=f"q_fix_{r.request_id}", disabled=not inv_no or amt is None):
                try:
                    store.resolve_exception(conn, r.request_id, inv_no.strip(), amt, ui.role(), now,
                                            "Corrected invoice recorded")
                    st.rerun()
                except ValueError as e:
                    st.error(ui.esc(e))
            st.caption(f"The corrected invoice must equal the request amount, ${r.total_amount:,.2f}.")
            ui.ask_assistant("Billing Quality", f"Explain the reconciliation exception on {r.request_id} in plain "
                                                "English and what a person should do next.",
                             label="Ask the assistant to explain")
ui.footer()
