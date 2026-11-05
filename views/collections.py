"""Collections: the Version 1 Collections worklist. The reminder is now drafted from a template."""
import streamlit as st

from core import receivables as rc
from views import common as ui

ui.filter_controls()
m = ui.metrics()
ui.header("Collections worklist", "Overdue accounts ranked by balance, with invoice detail for follow-up", reporting=True)

c = st.columns(4)
ui.kpi(c[0], "Overdue balance", rc.money(m.overdue_amt), f"{len(m.overdue):,} invoices", "bad", icon_name="clock")
ui.kpi(c[1], "Customers overdue", f"{m.overdue['CustomerName'].nunique():,}", "At least one overdue invoice", icon_name="users")
ui.kpi(c[2], "Active collection cases", f"{m.active_cases:,}", "Open, escalated, disputed or on a plan",
       icon_name="case", chip="warn")
ui.kpi(c[3], "Pending write-off review", f"{m.write_off_review:,}", "Cases recommended for write-off", icon_name="ban",
       chip="bad")

left, right = st.columns([3, 2])
with left:
    ui.section("Accounts to follow up", "Ranked by overdue balance")
    table = m.top_customers.head(15).rename(columns={"CustomerName": "Customer", "CustomerType": "Type",
                                                     "OverdueAR": "Overdue", "OldestDays": "Oldest (days)"})
    st.dataframe(table, hide_index=True, width="stretch", height=420,
                 column_config={"Overdue": st.column_config.NumberColumn(format="dollar")})
with right:
    ui.section("Overdue balance by customer type", "Where the overdue dollars sit")
    fig = ui.hbar(m.by_ctype.sort_values(), ui.BLUE)
    fig.update_xaxes(tickprefix="$", tickformat="~s")
    ui.chart(fig, 420)

st.subheader("Prepare a payment reminder")
if m.top_customers.empty:
    st.info("No overdue accounts for the selected filters.")
else:
    sel_col, tone_col = st.columns([2, 1])
    customer = sel_col.selectbox("Customer", m.top_customers["CustomerName"].tolist())
    tone = tone_col.selectbox("Reminder", ["First reminder", "Second reminder"])
    cust_inv = rc.overdue_invoices_for(m, customer)
    st.dataframe(cust_inv, hide_index=True, width="stretch",
                 column_config={"InvoiceID": "Invoice", "BillingCategory": "Category",
                                "Balance": st.column_config.NumberColumn(format="dollar"),
                                "InvoiceDate": st.column_config.DateColumn("Invoice date", format="YYYY-MM-DD"),
                                "DueDate": st.column_config.DateColumn("Due date", format="YYYY-MM-DD"),
                                "DaysPastDue": "Days past due"})
    subject, body = rc.reminder_email(customer, cust_inv, second=tone == "Second reminder")
    with st.container(border=True):
        st.text_input("Subject", subject, key=f"rem_subj_{customer}_{tone}")
        st.text_area("Draft email (edit before use)", body, height=300, key=f"rem_body_{customer}_{tone}")
        st.caption("Draft only. Nothing is sent from this app; an analyst reviews and sends reminders "
                   "from their own email.")
ui.ask_assistant("Collections")
ui.footer()
