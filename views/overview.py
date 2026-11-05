"""Executive Overview: the Version 1 Overview page, unchanged in content."""
import plotly.graph_objects as go
import streamlit as st

from core import receivables as rc
from views import common as ui

ui.filter_controls()
m = ui.metrics()
ui.header("Executive overview", "What has been billed, what has been collected, and what is still owed", reporting=True)

c = st.columns(5)
D = rc.DEFINITIONS
ui.kpi(c[0], "Total billed", rc.money(m.billed), f"{len(m.inv):,} invoices", help_text=D["Total billed"])
ui.kpi(c[1], "Collection rate", f"{m.collection_rate:.1%}" if m.billed else "-", f"{rc.money(m.collected)} collected",
       help_text=D["Collection rate"])
ui.kpi(c[2], "Outstanding", rc.money(m.outstanding), f"{len(m.unpaid):,} unpaid invoices", help_text=D["Outstanding"])
ui.kpi(c[3], "Overdue", rc.money(m.overdue_amt),
       f"{m.overdue_amt / m.outstanding:.0%} of outstanding" if m.outstanding else "", "bad", help_text=D["Overdue"])
ui.kpi(c[4], "Over 90 days", rc.money(m.over_90), f"{m.over_90_n:,} invoices", "bad", help_text=D["Over 90 days"])

if m.outstanding and len(m.by_category):
    ui.insight(f"<b>Key point:</b> {m.over_90 / m.outstanding:.0%} of the outstanding balance is more than 90 days "
               f"past due, and {m.by_category.index[0]} accounts for the largest share of overdue dollars "
               f"({rc.money(m.by_category['OverdueAR'].iloc[0])}).")

left, right = st.columns(2)
with left:
    ui.section("Outstanding balance by age", "Unpaid invoices grouped by days past their due date")
    fig = go.Figure(go.Bar(x=m.by_aging.index, y=m.by_aging.values, marker_color=ui.AGING_COLOURS,
                           text=[rc.money(v) for v in m.by_aging.values], textposition="outside",
                           hovertemplate="%{x} days: %{text}<extra></extra>"))
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    ui.chart(fig)
with right:
    ui.section("Overdue balance by billing category", "Open and disputed invoices past their due date")
    fig = ui.hbar(m.by_category["OverdueAR"].sort_values(), ui.BLUE)
    fig.update_xaxes(tickprefix="$", tickformat="~s")
    ui.chart(fig)

ui.section("Billed vs collected by month", "Value of invoices issued and payments received in each month")
trend = rc.monthly_trend(m)
fig = go.Figure([
    go.Bar(x=trend.index, y=trend["Billed"], name="Billed", marker_color=ui.LIGHT_BLUE,
           hovertemplate="Billed: %{y:$,.0f}<extra></extra>"),
    go.Bar(x=trend.index, y=trend["Collected"], name="Collected", marker_color=ui.NAVY,
           hovertemplate="Collected: %{y:$,.0f}<extra></extra>"),
])
fig.update_yaxes(tickprefix="$", tickformat="~s")
fig.update_xaxes(dtick="M2", tickformat="%b %Y")
fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.05, hovermode="x unified")
ui.chart(fig, 300)

with st.expander("How these figures are calculated"):
    for k in ["Total billed", "Collection rate", "Outstanding", "Overdue", "Over 90 days"]:
        st.markdown(f"- **{k}:** {D[k]}")
    st.caption("Reporting snapshot fixed at 30 Sep 2026. Open means status Open or Disputed.")
ui.ask_assistant("Executive Overview")
ui.footer()
