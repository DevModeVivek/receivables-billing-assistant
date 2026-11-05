"""Billing Operations: the Version 1 Billing operations page, unchanged in content."""
import plotly.graph_objects as go
import streamlit as st

from core import receivables as rc
from views import common as ui

ui.filter_controls()
m = ui.metrics()
ui.header("Billing operations", "How quickly completed work is invoiced, and where it gets held up", reporting=True)

D = rc.DEFINITIONS
c = st.columns(5)
ui.kpi(c[0], "Avg days to invoice", f"{m.cycle:.1f}", "From completed work", help_text=D["Avg days to invoice"])
ui.kpi(c[1], "Unbilled backlog", rc.money(m.unbilled), f"{len(m.pending):,} requests not yet invoiced",
       help_text=D["Unbilled backlog"])
ui.kpi(c[2], "Dispute rate", f"{m.dispute_rate:.1%}", f"{(m.inv['Status'] == 'Disputed').sum():,} disputed invoices",
       help_text=D["Dispute rate"])
ui.kpi(c[3], "Written off", rc.money(m.write_offs), f"{(m.inv['Status'] == 'Written Off').sum():,} invoices",
       help_text=D["Written off"])
if m.refund_recent == m.refund_recent and m.refund_before == m.refund_before:  # both not NaN
    ui.kpi(c[4], "Refund turnaround", f"{m.refund_recent:.0f} days",
           f"Was {m.refund_before:.0f} days in {rc.EARLIER_REFUNDS_LABEL}", "good", help_text=D["Refund turnaround"])
else:
    ui.kpi(c[4], "Refund turnaround", "-", "No refunds for this selection")

cyc = m.cycle_by_cat
if len(cyc) > 1:
    others = cyc.drop(cyc.index[-1]).mean()
    ui.insight(f"<b>Key point:</b> {cyc.index[-1]} takes {cyc.iloc[-1]:.0f} days on average to invoice, compared "
               f"with about {others:.0f} days for the other categories.")

left, right = st.columns(2)
with left:
    ui.section("Average days to invoice by category", "Dashed line shows the overall average")
    colours = [ui.RED if i == len(cyc) - 1 and len(cyc) > 1 else ui.BLUE for i in range(len(cyc))]
    fig = ui.hbar(cyc, ui.BLUE, fmt=lambda v: f"{v:.0f} days", colours=colours)
    fig.add_vline(x=m.cycle, line_dash="dash", line_color=ui.GREY, line_width=1)
    ui.chart(fig)
with right:
    ui.section("Unbilled backlog by category", "Estimated value of completed work waiting to be invoiced")
    fig = ui.hbar(m.pending.groupby("BillingCategory")["EstimatedAmount"].sum().sort_values(), ui.NAVY)
    fig.update_xaxes(tickprefix="$", tickformat="~s")
    ui.chart(fig)

left, right = st.columns(2)
with left:
    ui.section("Days to invoice by quarter", f"{rc.SLOW_CATEGORY} compared with all other categories")
    q = rc.slow_category_by_quarter(m)
    fig = go.Figure()
    for name, colour in [(rc.SLOW_CATEGORY, ui.RED), ("Other categories", ui.BLUE)]:
        if name in q.columns:
            fig.add_trace(go.Scatter(x=q.index, y=q[name], name=name, mode="lines+markers",
                                     line=dict(color=colour, width=2.5), marker=dict(size=7),
                                     hovertemplate="%{y:.0f} days<extra>" + name + "</extra>"))
    fig.update_yaxes(rangemode="tozero")
    ui.chart(fig, 300)
with right:
    ui.section("Refund approval time by quarter", "Average days from refund request to approval")
    r = rc.refund_by_quarter(m)
    fig = go.Figure(go.Bar(x=r.index, y=r.values, marker_color=[ui.GREY if v > 30 else ui.BLUE for v in r.values],
                           text=[f"{v:.0f}" for v in r.values], textposition="outside",
                           hovertemplate="%{x}: %{y:.0f} days<extra></extra>"))
    fig.add_hline(y=30, line_dash="dash", line_color=ui.GREY, line_width=1,
                  annotation_text="30-day target", annotation_position="top right")
    ui.chart(fig, 300)

with st.expander("How these figures are calculated"):
    for k in ["Avg days to invoice", "Unbilled backlog", "Dispute rate", "Written off", "Refund turnaround"]:
        st.markdown(f"- **{k}:** {D[k]}")
    st.caption("Refund turnaround compares requests from 1 Apr 2026 onward with requests before 1 Jul 2025. "
               "The 30-day target line is illustrative.")
ui.ask_assistant("Billing Operations")
ui.footer()
