"""Request Intake: a form, a spreadsheet upload or a pasted email. Everything is checked before it is saved."""
import pandas as pd
import streamlit as st

from ai.guard import MAX_EMAIL_CHARS
from ai.providers import AIError
from views import common as ui
from workflow import exports, extract, rules, sample_data, store

conn = ui.workspace()
customers = ui.customers()
today = ui.now().date()

ui.header("Request intake", "Log a billing request from a form, a spreadsheet or an email. The 16 checks run before "
                            "anything is saved.")


def preview(fields):
    req = {**store.clean_fields(fields), "request_id": "(new)", "received_at": ui.now().isoformat()}
    findings = store.findings_for(conn, req, customers, today)
    approved = False
    result = rules.readiness(findings, approved)
    st.markdown(f"Result: {ui.badge(result)}", unsafe_allow_html=True)
    for f in sorted(findings, key=lambda f: rules.SEVERITY_ORDER[f.severity]):
        st.markdown(f"{ui.badge(rules.SEVERITY_LABEL[f.severity])} {ui.esc(f.message)}", unsafe_allow_html=True)
    if not findings:
        st.caption("All 16 checks passed.")
    return findings


def saved(rid):
    req = store.get_request(conn, rid)
    st.success(f"Saved as {rid}. Status: {req['status']}. Open the Workflow Tracker to follow it.",
               icon=":material/check_circle:")


tab_form, tab_sheet, tab_email = st.tabs(["Form", "Spreadsheet", "Email"])

# ---------------------------------------------------------------- form
with tab_form:
    cat = st.selectbox("Billing category", rules.CATEGORIES, key="f_cat")
    need = set(rules.required_fields(cat))
    st.caption("Fields marked * are required for this category.")
    values = {"billing_category": cat}
    layout = [
        ("submitted_by_team", "select", rules.TEAMS), ("requester_name", "text", None),
        ("requester_email", "text", None), ("customer_account", "text", None), ("customer_name", "text", None),
        ("work_order", "text", None), ("work_completed_date", "date", None), ("cost_centre", "select", rules.COST_CENTRES),
        ("description", "text", None),
    ]
    extra = {"Third-Party Damage Recovery": [("incident_date", "date", None), ("claim_reference", "text", None),
                                             ("supporting_docs", "select", ["", "Yes", "No"])],
             "Joint-Use Pole Attachments": [("attachment_count", "number", None)],
             "Customer-Requested Work": [("quote_reference", "text", None)],
             "Connection & Capital Contributions": [("contract_number", "text", None)]}.get(cat, [])
    amounts = [] if cat == "Joint-Use Pole Attachments" else [("labour", "number", None), ("materials", "number", None),
                                                               ("equipment", "number", None)]
    cols = st.columns(3)
    for i, (f, kind, opts) in enumerate(layout + extra + amounts + [("total_amount", "number", None)]):
        label = rules.FIELD_LABELS[f] + (" *" if f in need else "")
        col = cols[i % 3]
        key = f"f_{f}"
        if kind == "select":
            values[f] = col.selectbox(label, [""] + [o for o in opts if o], key=key) or None
        elif kind == "date":
            v = col.date_input(label, value=None, key=key, format="YYYY-MM-DD")
            values[f] = v.isoformat() if v else None
        elif kind == "number":
            values[f] = col.number_input(label, value=None, min_value=0.0, step=1.0 if f == "attachment_count" else 0.01,
                                         key=key, format="%.0f" if f == "attachment_count" else "%.2f")
        else:
            values[f] = col.text_input(label, key=key, max_chars=200) or None
    if cat == "Joint-Use Pole Attachments":
        st.caption(f"Illustrative rate card: ${rules.POLE_ATTACHMENT_RATE:.2f} per attachment.")
    if st.button("Check request", key="f_check"):
        st.session_state["f_checked"] = dict(values)
    if st.session_state.get("f_checked"):
        with st.container(border=True):
            preview(st.session_state["f_checked"])
            if st.button("Save request", type="primary", key="f_save"):
                rid, _ = store.add_request(conn, st.session_state.pop("f_checked"), "Intake form", ui.role(),
                                           ui.now(), customers)
                saved(rid)

# ---------------------------------------------------------------- spreadsheet
with tab_sheet:
    st.markdown("Upload a CSV or Excel file with one request per row. Column headers can be the field names or the "
                f"labels used in the template. Limit: {exports.MAX_UPLOAD_ROWS} rows, 1 MB.")
    template = pd.DataFrame(columns=[rules.FIELD_LABELS[f] for f in rules.REQUEST_FIELDS])
    c1, c2, _ = st.columns([1, 1, 2])
    c1.download_button("Download blank template", exports.to_excel_bytes(template, "Requests"),
                       "billing_request_template.xlsx", key="s_tpl")
    use_sample = c2.button("Use a sample spreadsheet", key="s_sample")
    upload = st.file_uploader("Spreadsheet", type=["csv", "xlsx"], key="s_upload", label_visibility="collapsed")
    df = None
    if use_sample:
        st.session_state["s_df"] = sample_data.sample_spreadsheet(today)
        st.session_state["s_name"] = "Sample: six requests from the Lines team"
    if upload is not None:
        try:
            raw = exports.read_upload(upload.name, upload.getvalue())
            mapped = exports.match_columns(raw, rules.FIELD_LABELS)
            if mapped is None:
                st.error("No recognised columns. Please start from the template.")
            else:
                st.session_state["s_df"] = mapped.rename(columns=rules.FIELD_LABELS)
                st.session_state["s_name"] = upload.name
        except exports.UploadError as e:
            st.error(ui.esc(e))
    df = st.session_state.get("s_df")
    if df is not None:
        st.caption(st.session_state.get("s_name", ""))
        label_to_field = {v: k for k, v in rules.FIELD_LABELS.items()}
        rows = df.rename(columns=label_to_field).to_dict("records")
        results = []
        for i, row in enumerate(rows, 1):
            req = {**store.clean_fields(row), "request_id": f"(row {i})", "received_at": ui.now().isoformat()}
            fs = store.findings_for(conn, req, customers, today)
            results.append({"Row": i, "Customer": req.get("customer_name") or req.get("customer_account"),
                            "Category": req.get("billing_category"), "Amount": req.get("total_amount"),
                            "Result": rules.readiness(fs, False),
                            "Problems": "; ".join(f.message for f in fs if f.severity != "Warning") or "None"})
        st.dataframe(pd.DataFrame(results), hide_index=True, width="stretch",
                     column_config={"Amount": st.column_config.NumberColumn(format="dollar")})
        if st.button(f"Save all {len(rows)} requests", type="primary", key="s_save"):
            ids = [store.add_request(conn, r, "Spreadsheet", ui.role(), ui.now(), customers)[0] for r in rows]
            st.session_state.pop("s_df", None)
            st.success(f"Saved {len(ids)} requests ({ids[0]} to {ids[-1]}). Requests with problems are on hold "
                       "with a follow-up ready in the Workflow Tracker.", icon=":material/check_circle:")

# ---------------------------------------------------------------- email
with tab_email:
    provider = ui.ai_provider()
    sample = st.selectbox("Start from a sample email (optional)", [""] + list(sample_data.SAMPLE_EMAILS), key="e_sample")
    if sample and st.session_state.get("e_loaded") != sample:
        st.session_state["e_text"] = sample_data.sample_email(sample, today)
        st.session_state["e_loaded"] = sample
    text = st.text_area("Paste the email", key="e_text", height=260, max_chars=MAX_EMAIL_CHARS)
    st.caption("Template emails are read directly. Free-text emails are read by AI, and every value is checked "
               "against the email." if provider else "Template emails are read directly. Fill any gaps by hand.")
    if st.button("Read email", key="e_read", disabled=not text.strip()):
        try:
            fields, source = extract.read_email(text, provider)
            st.session_state["e_fields"] = (fields, source)
        except AIError:
            fields, source = extract.read_email(text, None)
            st.session_state["e_fields"] = (fields, source)
            st.info("The AI is busy right now, so the template reader was used. Fill any gaps by hand.",
                    icon=":material/info:")
    if st.session_state.get("e_fields"):
        fields, source = st.session_state["e_fields"]
        table = pd.DataFrame([{"Field": rules.FIELD_LABELS[f], "Value": "" if fields.get(f) is None else str(fields.get(f)),
                               "Read by": source.get(f, "")} for f in rules.REQUEST_FIELDS])
        st.markdown("Check and correct the fields. Values marked **AI - not found in email** must be checked.")
        edited = st.data_editor(table, hide_index=True, width="stretch", disabled=["Field", "Read by"], key="e_edit")
        label_to_field = {v: k for k, v in rules.FIELD_LABELS.items()}
        final = {label_to_field[r.Field]: (r.Value or None) for r in edited.itertuples()}
        with st.container(border=True):
            preview(final)
            if st.button("Save request", type="primary", key="e_save"):
                rid, _ = store.add_request(conn, final, "Email", ui.role(), ui.now(), customers)
                st.session_state.pop("e_fields", None)
                saved(rid)
ui.footer()
