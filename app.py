"""Receivables & Billing Insights.

Billing and accounts receivable analysis with a local AI assistant.
All figures are calculated in pandas; the local model (Ollama) only explains
them and drafts text. The app runs fully offline on sample data.
"""
from datetime import date
from pathlib import Path

import ollama
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA_FILE = Path(__file__).parent / "data" / "billing_sample_data.xlsx"
AS_OF = pd.Timestamp(date(2026, 9, 30))
OPEN_STATUSES = ["Open", "Disputed"]
AGING_ORDER = ["Current", "1-30", "31-60", "61-90", "90+"]
SLOW_CATEGORY = "Third-Party Damage Recovery"

NAVY = "#14365D"
BLUE = "#2F6DB5"
LIGHT_BLUE = "#A9C4E6"
GREY = "#8A94A3"
RED = "#B03A2E"
AGING_COLOURS = ["#A9C4E6", "#6E9BD1", "#2F6DB5", "#C9772B", "#B03A2E"]

st.set_page_config(page_title="Receivables & Billing Insights", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
<style>
.block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1400px;}
h1 {font-size: 1.6rem !important; font-weight: 600 !important; color: #14365D;}
h3 {font-size: 1.0rem !important; font-weight: 600 !important; color: #1F2A37; padding-top: 1.4rem !important;}
section[data-testid="stSidebar"] {background: #F5F7FA; border-right: 1px solid #E3E8EF;}
.page-sub {color: #6B7785; font-size: 0.9rem; margin-top: -0.6rem; margin-bottom: 1.4rem;}
.kpi {background: #FFFFFF; border: 1px solid #E3E8EF; border-radius: 8px; padding: 16px 18px; min-height: 112px;}
.kpi-label {color: #6B7785; font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.04em;}
.kpi-value {color: #14365D; font-size: 1.6rem; font-weight: 600; margin-top: 6px;}
.kpi-note {color: #6B7785; font-size: 0.8rem; margin-top: 4px;}
.kpi-note.bad {color: #B03A2E;}
.kpi-note.good {color: #2E7D4F;}
.panel-note {color: #6B7785; font-size: 0.82rem; margin-top: -0.5rem;}
.insight {background: #F5F8FC; border-left: 3px solid #2F6DB5; padding: 10px 14px; border-radius: 4px;
          color: #1F2A37; font-size: 0.9rem; margin: 1.2rem 0 1rem 0;}
div.stButton > button {border: 1px solid #D5DDE8; background: #FFFFFF; color: #14365D; border-radius: 6px;
                       justify-content: flex-start;}
div.stButton > button p {text-align: left; font-size: 0.88rem;}
div.stButton > button:hover {border-color: #2F6DB5; color: #2F6DB5;}
div[data-testid="stChatMessage"] {background: #FFFFFF; border: 1px solid #E3E8EF; border-radius: 8px;
                                  padding: 14px 18px; margin-bottom: 0.6rem;}
div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {background: #F5F7FA;
                                                                             border-color: #F5F7FA;}
[data-testid="stChatMessageAvatarUser"] {background: #D5DDE8 !important; color: #14365D !important;}
[data-testid="stChatMessageAvatarAssistant"] {background: #14365D !important; color: #FFFFFF !important;}
.footer {color: #9AA4B2; font-size: 0.75rem; margin-top: 2.5rem; border-top: 1px solid #EEF1F5; padding-top: 0.8rem;}
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- data
@st.cache_data
def load_data():
    sheets = pd.read_excel(DATA_FILE, sheet_name=None)
    customers = sheets["Customers"][["CustomerID", "CustomerName", "CustomerType", "Region"]]
    inv = sheets["Invoices"].merge(customers.drop(columns="Region"), on="CustomerID")
    inv["Balance"] = inv["InvoiceAmount"] - inv["AmountPaid"]
    inv["DaysPastDue"] = (AS_OF - inv["DueDate"]).dt.days
    inv["BillingCycleDays"] = (inv["InvoiceDate"] - inv["WorkCompletedDate"]).dt.days
    inv["Month"] = inv["InvoiceDate"].dt.to_period("M").dt.to_timestamp()
    inv["Quarter"] = inv["InvoiceDate"].dt.to_period("Q")
    inv["AgingBucket"] = pd.cut(inv["DaysPastDue"], [-10_000, 0, 30, 60, 90, 10_000], labels=AGING_ORDER).astype(str)
    inv.loc[~inv["Status"].isin(OPEN_STATUSES), "AgingBucket"] = None
    pay = sheets["Payments"].merge(inv[["InvoiceID", "Region", "BillingCategory", "CustomerType"]], on="InvoiceID")
    pay["Month"] = pay["PaymentDate"].dt.to_period("M").dt.to_timestamp()
    req = sheets["BillingRequests"].merge(customers[["CustomerID", "CustomerType"]], on="CustomerID")
    cases = sheets["CollectionCases"]
    refunds = sheets["Refunds"].merge(customers, on="CustomerID")
    refunds["DaysToApprove"] = (refunds["ApprovalDate"] - refunds["RequestDate"]).dt.days
    refunds["Quarter"] = refunds["RequestDate"].dt.to_period("Q")
    return inv, pay, req, cases, refunds


def money(x):
    if abs(x) >= 1_000_000:
        return f"${x / 1_000_000:,.2f}M"
    if abs(x) >= 1_000:
        return f"${x / 1_000:,.0f}K"
    return f"${x:,.0f}"


def kpi(col, label, value, note="", tone=""):
    col.markdown(
        f"<div class='kpi'><div class='kpi-label'>{label}</div><div class='kpi-value'>{value}</div>"
        f"<div class='kpi-note {tone}'>{note}</div></div>",
        unsafe_allow_html=True,
    )


def section(title, note):
    st.subheader(title)
    st.markdown(f"<div class='panel-note'>{note}</div>", unsafe_allow_html=True)


def chart(fig, height=320):
    fig.update_layout(
        template="simple_white", height=height, margin=dict(l=8, r=70, t=28, b=8),
        paper_bgcolor="white", plot_bgcolor="white",
        font=dict(family="Source Sans Pro, Segoe UI, sans-serif", size=12, color="#1F2A37"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        hoverlabel=dict(bgcolor="white"), bargap=0.35,
    )
    fig.update_xaxes(showgrid=False, title=None, linecolor="#D5DDE8", ticks="")
    fig.update_yaxes(gridcolor="#EEF1F5", showgrid=True, title=None, linecolor="#D5DDE8", ticks="")
    fig.update_traces(selector=dict(type="bar"), cliponaxis=False)
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False})


def hbar(series, colour, fmt=money, colours=None):
    fig = go.Figure(go.Bar(x=series.values, y=series.index, orientation="h", marker_color=colours or colour,
                           text=[fmt(v) for v in series.values], textposition="outside",
                           hovertemplate="%{y}: %{text}<extra></extra>"))
    fig.update_xaxes(showgrid=True, gridcolor="#EEF1F5")
    fig.update_yaxes(showgrid=False)
    return fig


def quarter_labels(periods):
    return [f"Q{p.quarter} {p.year}" for p in periods]


def local_models():
    listing = ollama.list()
    items = listing.models if hasattr(listing, "models") else listing.get("models", [])
    return [getattr(m, "model", None) or m.get("name") for m in items]


def stream_answer(model, system_prompt, history):
    """Stream the model's reply. Dollar signs are escaped so Markdown does not treat them as maths."""
    messages = [{"role": "system", "content": system_prompt}] + history
    stream = ollama.chat(model=model, messages=messages, stream=True)
    shown = st.write_stream(chunk["message"]["content"].replace("$", "\\$") for chunk in stream)
    return shown.replace("\\$", "$")


inv_all, pay_all, req_all, cases_all, refunds_all = load_data()

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("<div style='font-weight:600;font-size:1.05rem;color:#14365D'>Receivables & Billing</div>"
                "<div style='color:#6B7785;font-size:0.8rem;margin-bottom:1rem'>Customer Operations Analytics</div>",
                unsafe_allow_html=True)
    page = st.radio("Page", ["Overview", "Billing operations", "Collections", "Assistant"], label_visibility="collapsed")
    st.markdown("---")
    st.caption("FILTERS")
    regions = st.multiselect("Region", sorted(inv_all["Region"].unique()), placeholder="All regions")
    categories = st.multiselect("Billing category", sorted(inv_all["BillingCategory"].unique()),
                                placeholder="All categories")
    ctypes = st.multiselect("Customer type", sorted(inv_all["CustomerType"].unique()), placeholder="All types")
    st.markdown("---")
    st.caption("ASSISTANT")
    try:
        models = local_models()
        model = st.selectbox("Local model", models) if models else None
    except Exception:
        models, model = [], None
    if not model:
        st.caption("Local model unavailable. Start Ollama to use the assistant.")


def apply_filters(df):
    for column, chosen in [("Region", regions), ("BillingCategory", categories), ("CustomerType", ctypes)]:
        if chosen and column in df.columns:
            df = df[df[column].isin(chosen)]
    return df


inv, pay, req, refunds = (apply_filters(d) for d in (inv_all, pay_all, req_all, refunds_all))
cases = cases_all[cases_all["InvoiceID"].isin(inv["InvoiceID"])]
unpaid = inv[inv["Status"].isin(OPEN_STATUSES)]
overdue = unpaid[unpaid["DaysPastDue"] > 0]

billed = inv["InvoiceAmount"].sum()
collected = pay["AmountPaid"].sum()
outstanding = unpaid["Balance"].sum()
overdue_amt = overdue["Balance"].sum()
over_90 = unpaid.loc[unpaid["AgingBucket"] == "90+", "Balance"].sum()
over_90_n = (unpaid["AgingBucket"] == "90+").sum()
avg_dpd = overdue["DaysPastDue"].mean() if len(overdue) else 0
cycle = inv["BillingCycleDays"].mean() if len(inv) else 0
pending = req[req["RequestStatus"] == "Pending Invoice"]
unbilled = pending["EstimatedAmount"].sum()
write_offs = inv.loc[inv["Status"] == "Written Off", "InvoiceAmount"].sum()
dispute_rate = (inv["Status"] == "Disputed").mean() if len(inv) else 0
refund_recent = refunds.loc[refunds["RequestDate"] >= "2026-04-01", "DaysToApprove"].mean()
refund_before = refunds.loc[refunds["RequestDate"] < "2025-07-01", "DaysToApprove"].mean()

by_category = (overdue.groupby("BillingCategory")
               .agg(OverdueAR=("Balance", "sum"), Invoices=("InvoiceID", "count"))
               .sort_values("OverdueAR", ascending=False))
by_aging = unpaid.groupby("AgingBucket")["Balance"].sum().reindex(AGING_ORDER).fillna(0)
cycle_by_cat = inv.groupby("BillingCategory")["BillingCycleDays"].mean().sort_values()
by_ctype = overdue.groupby("CustomerType")["Balance"].sum().sort_values(ascending=False)
by_region = overdue.groupby("Region")["Balance"].sum().sort_values(ascending=False)
top_customers = (overdue.groupby(["CustomerName", "CustomerType"])
                 .agg(OverdueAR=("Balance", "sum"), Invoices=("InvoiceID", "count"),
                      OldestDays=("DaysPastDue", "max"))
                 .sort_values("OverdueAR", ascending=False).reset_index())

filters_text = ", ".join(regions + categories + ctypes) or "All regions and categories"


def header(title, subtitle):
    st.title(title)
    st.markdown(f"<div class='page-sub'>{subtitle} &nbsp;·&nbsp; As of 30 Sep 2026 &nbsp;·&nbsp; {filters_text}</div>",
                unsafe_allow_html=True)


# ---------------------------------------------------------------- pages
if page == "Overview":
    header("Receivables overview", "What has been billed, what has been collected, and what is still owed")
    c = st.columns(5)
    kpi(c[0], "Total billed", money(billed), f"{len(inv):,} invoices")
    kpi(c[1], "Collection rate", f"{collected / billed:.1%}" if billed else "-", f"{money(collected)} collected")
    kpi(c[2], "Outstanding", money(outstanding), f"{len(unpaid):,} unpaid invoices")
    kpi(c[3], "Overdue", money(overdue_amt), f"{overdue_amt / outstanding:.0%} of outstanding" if outstanding else "",
        "bad")
    kpi(c[4], "Over 90 days", money(over_90), f"{over_90_n:,} invoices", "bad")

    if outstanding and len(by_category):
        st.markdown(f"<div class='insight'><b>Key point:</b> {over_90 / outstanding:.0%} of the outstanding balance "
                    f"is more than 90 days past due, and {by_category.index[0]} accounts for the largest share of "
                    f"overdue dollars ({money(by_category['OverdueAR'].iloc[0])}).</div>", unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        section("Outstanding balance by age", "Unpaid invoices grouped by days past their due date")
        fig = go.Figure(go.Bar(x=by_aging.index, y=by_aging.values, marker_color=AGING_COLOURS,
                               text=[money(v) for v in by_aging.values], textposition="outside",
                               hovertemplate="%{x} days: %{text}<extra></extra>"))
        fig.update_yaxes(tickprefix="$", tickformat="~s")
        chart(fig)
    with right:
        section("Overdue balance by billing category", "Open and disputed invoices past their due date")
        fig = hbar(by_category["OverdueAR"].sort_values(), BLUE)
        fig.update_xaxes(tickprefix="$", tickformat="~s")
        chart(fig)

    section("Billed vs collected by month", "Value of invoices issued and payments received in each month")
    trend = pd.DataFrame({"Billed": inv.groupby("Month")["InvoiceAmount"].sum(),
                          "Collected": pay.groupby("Month")["AmountPaid"].sum()}).fillna(0)
    trend = trend[trend.index <= AS_OF]
    fig = go.Figure([
        go.Bar(x=trend.index, y=trend["Billed"], name="Billed", marker_color=LIGHT_BLUE,
               hovertemplate="Billed: %{y:$,.0f}<extra></extra>"),
        go.Bar(x=trend.index, y=trend["Collected"], name="Collected", marker_color=NAVY,
               hovertemplate="Collected: %{y:$,.0f}<extra></extra>"),
    ])
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    fig.update_xaxes(dtick="M2", tickformat="%b %Y")
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.05, hovermode="x unified")
    chart(fig, 300)

elif page == "Billing operations":
    header("Billing operations", "How quickly completed work is invoiced, and where it gets held up")
    c = st.columns(5)
    kpi(c[0], "Avg days to invoice", f"{cycle:.1f}", "From completed work")
    kpi(c[1], "Unbilled backlog", money(unbilled), f"{len(pending):,} requests not yet invoiced")
    kpi(c[2], "Dispute rate", f"{dispute_rate:.1%}", f"{(inv['Status'] == 'Disputed').sum():,} disputed invoices")
    kpi(c[3], "Written off", money(write_offs), f"{(inv['Status'] == 'Written Off').sum():,} invoices")
    if pd.notna(refund_recent) and pd.notna(refund_before):
        kpi(c[4], "Refund turnaround", f"{refund_recent:.0f} days", f"Was {refund_before:.0f} days in early 2025",
            "good")
    else:
        kpi(c[4], "Refund turnaround", "-", "No refunds for this selection")

    if len(cycle_by_cat) > 1:
        others = cycle_by_cat.drop(cycle_by_cat.index[-1]).mean()
        st.markdown(f"<div class='insight'><b>Key point:</b> {cycle_by_cat.index[-1]} takes "
                    f"{cycle_by_cat.iloc[-1]:.0f} days on average to invoice, compared with about {others:.0f} days "
                    f"for the other categories.</div>",
                    unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        section("Average days to invoice by category", "Dashed line shows the overall average")
        colours = [RED if i == len(cycle_by_cat) - 1 and len(cycle_by_cat) > 1 else BLUE
                   for i in range(len(cycle_by_cat))]
        fig = hbar(cycle_by_cat, BLUE, fmt=lambda v: f"{v:.0f} days", colours=colours)
        fig.add_vline(x=cycle, line_dash="dash", line_color=GREY, line_width=1)
        chart(fig)
    with right:
        section("Unbilled backlog by category", "Estimated value of completed work waiting to be invoiced")
        fig = hbar(pending.groupby("BillingCategory")["EstimatedAmount"].sum().sort_values(), NAVY)
        fig.update_xaxes(tickprefix="$", tickformat="~s")
        chart(fig)

    left, right = st.columns(2)
    with left:
        section("Days to invoice by quarter", f"{SLOW_CATEGORY} compared with all other categories")
        q = inv.assign(Group=inv["BillingCategory"].where(inv["BillingCategory"] == SLOW_CATEGORY, "Other categories"))
        q = q.groupby(["Quarter", "Group"])["BillingCycleDays"].mean().unstack()
        q.index = quarter_labels(q.index)
        fig = go.Figure()
        for name, colour in [(SLOW_CATEGORY, RED), ("Other categories", BLUE)]:
            if name in q.columns:
                fig.add_trace(go.Scatter(x=q.index, y=q[name], name=name, mode="lines+markers",
                                         line=dict(color=colour, width=2.5), marker=dict(size=7),
                                         hovertemplate="%{y:.0f} days<extra>" + name + "</extra>"))
        fig.update_yaxes(rangemode="tozero")
        chart(fig, 300)
    with right:
        section("Refund approval time by quarter", "Average days from refund request to approval")
        r = refunds.groupby("Quarter")["DaysToApprove"].mean().dropna()
        r.index = quarter_labels(r.index)
        fig = go.Figure(go.Bar(x=r.index, y=r.values, marker_color=[GREY if v > 30 else BLUE for v in r.values],
                               text=[f"{v:.0f}" for v in r.values], textposition="outside",
                               hovertemplate="%{x}: %{y:.0f} days<extra></extra>"))
        fig.add_hline(y=30, line_dash="dash", line_color=GREY, line_width=1,
                      annotation_text="30-day target", annotation_position="top right")
        chart(fig, 300)

elif page == "Collections":
    header("Collections worklist", "Overdue accounts ranked by balance, with invoice detail for follow-up")
    open_cases = cases["CaseStatus"].isin(["Open", "Escalated", "Payment Plan", "Dispute Under Review"]).sum()
    c = st.columns(4)
    kpi(c[0], "Overdue balance", money(overdue_amt), f"{len(overdue):,} invoices", "bad")
    kpi(c[1], "Customers overdue", f"{overdue['CustomerName'].nunique():,}", "At least one overdue invoice")
    kpi(c[2], "Active collection cases", f"{open_cases:,}", "Open, escalated, disputed or on a plan")
    kpi(c[3], "Pending write-off review", f"{(cases['CaseStatus'] == 'Write-Off Recommended').sum():,}",
        "Cases recommended for write-off")

    left, right = st.columns([3, 2])
    with left:
        section("Accounts to follow up", "Ranked by overdue balance")
        table = top_customers.head(15).rename(columns={"CustomerName": "Customer", "CustomerType": "Type",
                                                       "OverdueAR": "Overdue", "OldestDays": "Oldest (days)"})
        st.dataframe(table, hide_index=True, width="stretch", height=420,
                     column_config={"Overdue": st.column_config.NumberColumn(format="dollar")})
    with right:
        section("Overdue balance by customer type", "Where the overdue dollars sit")
        fig = hbar(by_ctype.sort_values(), BLUE)
        fig.update_xaxes(tickprefix="$", tickformat="~s")
        chart(fig, 420)

    st.subheader("Prepare a payment reminder")
    if top_customers.empty:
        st.info("No overdue accounts for the selected filters.")
    else:
        sel_col, tone_col = st.columns([2, 1])
        customer = sel_col.selectbox("Customer", top_customers["CustomerName"].tolist())
        tone = tone_col.selectbox("Reminder", ["First reminder", "Second reminder"])
        cust_inv = (overdue[overdue["CustomerName"] == customer]
                    [["InvoiceID", "BillingCategory", "InvoiceDate", "DueDate", "Balance", "DaysPastDue", "Status"]]
                    .sort_values("DaysPastDue", ascending=False))
        st.dataframe(cust_inv, hide_index=True, width="stretch",
                     column_config={"InvoiceID": "Invoice", "BillingCategory": "Category",
                                    "Balance": st.column_config.NumberColumn(format="dollar"),
                                    "InvoiceDate": st.column_config.DateColumn("Invoice date", format="YYYY-MM-DD"),
                                    "DueDate": st.column_config.DateColumn("Due date", format="YYYY-MM-DD"),
                                    "DaysPastDue": "Days past due"})
        if st.button("Draft reminder email", disabled=model is None):
            prompt = (
                "You write payment reminder emails for a utility's billing team. Use only the invoice details "
                "provided. Be courteous, clear and professional. List each invoice with its amount and due date, "
                "state the total, and invite the customer to pay or to contact the billing team if they have a "
                "question about the charges. A second reminder is firmer and asks for payment within 10 business "
                "days. Sign off as 'Billing Operations'. Keep it under 170 words. Output only the email."
            )
            details = cust_inv.assign(InvoiceDate=cust_inv["InvoiceDate"].dt.date,
                                      DueDate=cust_inv["DueDate"].dt.date).to_string(index=False)
            with st.container(border=True):
                stream_answer(model, prompt, [{"role": "user", "content":
                                               f"{tone} to {customer}.\nOverdue invoices:\n{details}\n"
                                               f"Total overdue: ${cust_inv['Balance'].sum():,.2f}"}])
            st.caption("Draft for review. An analyst checks every email before it is sent.")

else:
    header("Assistant", "Ask questions about the current selection in plain English")
    # One plain line per fact, so a small local model reads each value with its correct label.
    sections = {
        "Overdue balance by billing category": [
            f"{cat}: ${row.OverdueAR:,.0f} across {row.Invoices} invoices" for cat, row in by_category.iterrows()],
        "Outstanding balance by age (days past due)": [f"{b}: ${v:,.0f}" for b, v in by_aging.items()],
        "Average days to invoice by category": [f"{cat}: {v:.1f} days" for cat, v in cycle_by_cat.items()],
        "Overdue balance by customer type": [f"{t}: ${v:,.0f}" for t, v in by_ctype.items()],
        "Overdue balance by region": [f"{r}: ${v:,.0f}" for r, v in by_region.items()],
        "Top 10 overdue customers, largest first": [
            f"{row.CustomerName} (customer type: {row.CustomerType}): ${row.OverdueAR:,.0f} overdue across "
            f"{row.Invoices} invoices, oldest invoice {row.OldestDays} days past due"
            for row in top_customers.head(10).itertuples()],
    }
    metrics = {
        "Total billed": f"${billed:,.0f}", "Collected": f"${collected:,.0f}",
        "Collection rate": f"{collected / billed:.1%}" if billed else "-",
        "Outstanding": f"${outstanding:,.0f}", "Overdue": f"${overdue_amt:,.0f}",
        "Over 90 days past due": f"${over_90:,.0f}", "Average days past due (overdue invoices)": f"{avg_dpd:.0f}",
        "Average days to invoice": f"{cycle:.1f}", "Unbilled backlog": f"${unbilled:,.0f}",
        "Written off": f"${write_offs:,.0f}", "Dispute rate": f"{dispute_rate:.1%}",
        "Refund turnaround, last two quarters (days)": f"{refund_recent:.0f}" if pd.notna(refund_recent) else "-",
    }
    context = (f"Data as of 30 Sep 2026. Current filter: {filters_text}.\n"
               + "\n".join(f"- {k}: {v}" for k, v in metrics.items()) + "\n\n"
               + "\n\n".join(f"{name}:\n" + ("\n".join(f"- {line}" for line in lines) or "- none")
                              for name, lines in sections.items()))
    system_prompt = (
        "You are an analyst supporting a utility's billing and accounts receivable team. The team bills for "
        "third-party damage recovery, pole attachments, customer-requested work and connection fees. "
        "Answer only from the data provided. Copy names, customer types and figures exactly as written, "
        "with dollar amounts as whole dollars. If the data does not cover the question, say so and name the "
        "data that would be needed. Write for a finance manager: short, specific, and in bullet points where "
        "helpful. Do not add greetings or closing lines.\n\n" + context
    )

    if model is None:
        st.warning("The local model is not running. Open Ollama and refresh the page to use the assistant.")
    else:
        st.session_state.setdefault("chat", [])
        question = st.chat_input("Ask about billing, collections or receivables") or st.session_state.pop(
            "pending", None)

        if not st.session_state["chat"] and not question:
            st.markdown("<div class='panel-note' style='margin:0 0 0.8rem 0'>Answers use the calculated figures "
                        "for the current filters. The model explains the numbers; it does not calculate them."
                        "</div>", unsafe_allow_html=True)
            st.markdown("**Suggested questions**")
            suggestions = [
                "Where should collections focus first to reduce overdue balances?",
                "Summarise the receivables position for a weekly leadership update.",
                "Why is the slowest category taking longer to invoice, and what could be automated?",
                "Which customers should be contacted this week, and why?",
            ]
            cols = st.columns(2)
            for i, q in enumerate(suggestions):
                cols[i % 2].button(q, key=f"s{i}", width="stretch",
                                   on_click=lambda q=q: st.session_state.update(pending=q))

        for msg in st.session_state["chat"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"].replace("$", "\\$"))

        if question:
            st.session_state["chat"].append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question.replace("$", "\\$"))
            with st.chat_message("assistant"):
                answer = stream_answer(model, system_prompt, st.session_state["chat"])
            st.session_state["chat"].append({"role": "assistant", "content": answer})

        if st.session_state["chat"]:
            if st.button("New conversation"):
                st.session_state["chat"] = []
                st.rerun()

    with st.expander("Data provided to the assistant"):
        st.caption("The assistant only sees these calculated summaries, not the raw records.")
        st.text(context)

st.markdown("<div class='footer'>Sample data for demonstration · Figures calculated in Python (pandas) · "
            "Assistant runs locally with Ollama, so no data leaves this computer</div>", unsafe_allow_html=True)
