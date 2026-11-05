"""Process Insights: how the billing request process is performing, with a definition for every measure."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views import common as ui
from workflow import rules, store

conn = ui.workspace()
reqs = store.table(conn, "SELECT * FROM requests")
checks = store.table(conn, "SELECT * FROM checks_log WHERE run_no = 1")
events = store.table(conn, "SELECT * FROM events")

ui.header("Process insights", "How the billing request process is performing in the demo workspace")
st.caption("Simulated demo requests. These show how each measure would be tracked in a pilot, not real results.")

first = reqs[reqs["first_pass_clean"].notna()]
billed = reqs[reqs["status"] == "Billed"]
days = (pd.to_datetime(billed["billed_at"]) - pd.to_datetime(billed["received_at"])).dt.total_seconds() / 86400
blockers = checks[checks["severity"] == "Blocker"]
keying = int((events["action"] == "Reconciliation exception").sum())
followups = int(reqs["followups_sent"].fillna(0).sum())

MEASURES = [
    ("Requests received", f"{len(reqs)}", "Every request logged in the demo period, from any source."),
    ("Complete first time", f"{first['first_pass_clean'].mean():.0%}" if len(first) else "-",
     "Share of requests with no Must fix problem on their first check."),
    ("Median days to invoice", f"{days.median():.1f}" if len(days) else "-",
     "Median calendar days from request received to invoice confirmed, for billed requests."),
    ("Problems caught at intake", f"{len(blockers)}", "Must fix problems found on first check, before billing."),
    ("Keying errors caught", f"{keying}", "Invoices that did not match their request at reconciliation."),
    ("Follow-ups and reminders", f"{followups}", "Emails recorded as sent to requesters for missing information."),
]
cols = st.columns(len(MEASURES))
for col, (label, value, definition) in zip(cols, MEASURES):
    ui.kpi(col, label, value, help_text=definition)

with st.expander("Definitions", expanded=False):
    for label, _, definition in MEASURES:
        st.markdown(f"- **{label}:** {definition}")

left, right = st.columns(2)
with left:
    ui.section("Requests received per week", "By the week the request arrived")
    wk = pd.to_datetime(reqs["received_at"]).dt.to_period("W").dt.start_time.value_counts().sort_index()
    fig = go.Figure(go.Bar(x=wk.index, y=wk.values, marker_color=ui.BLUE, text=wk.values, textposition="outside",
                           hovertemplate="Week of %{x|%d %b}: %{y}<extra></extra>"))
    fig.update_xaxes(tickformat="%d %b")
    ui.chart(fig, 300)
with right:
    ui.section("Most common problems at intake", "Must fix problems on first check")

    def label(row):
        return ("Missing " + rules.FIELD_LABELS[row.field].lower()) if row.rule_id == "REQ" else \
            rules.PROBLEM_LABEL.get(row.rule_id, row.rule_id)

    if len(blockers):
        top = blockers.apply(label, axis=1).value_counts().head(7).sort_values()
        ui.chart(ui.hbar(top, ui.NAVY, fmt=lambda v: f"{v:.0f}"), 300)
    else:
        st.caption("No problems recorded yet.")

ui.section("Complete first time, by submitting team", "Teams with lower rates are where better templates or "
                                                      "training would help most")
by_team = first.groupby("submitted_by_team")["first_pass_clean"].agg(["mean", "count"]).sort_values("mean")
if len(by_team):
    fig = ui.hbar(by_team["mean"], ui.BLUE, fmt=lambda v: f"{v:.0%}",
                  colours=[ui.AMBER if v < 0.6 else ui.BLUE for v in by_team["mean"]])
    fig.update_xaxes(tickformat=".0%", range=[0, 1.1])
    ui.chart(fig, 280)
    st.caption("Amber bars are below 60%. Sample sizes: " +
               ", ".join(f"{t} {int(n)}" for t, n in by_team["count"].items()) + " requests.")
ui.ask_assistant("Process Insights")
ui.footer()
