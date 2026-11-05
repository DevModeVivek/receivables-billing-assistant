"""Home: a personal introduction, the key figures, today's priorities and the guided demo."""
import streamlit as st

from core import receivables as rc
from views import common as ui
from workflow import store

m = ui.metrics(rc.Filters())  # headline figures always use the full portfolio
conn = ui.workspace()
reqs = store.table(conn, "SELECT status, exception FROM requests")
counts = reqs["status"].value_counts()
exceptions = int(reqs["exception"].notna().sum())

st.title("Receivables & Billing Insights")
st.markdown("<div class='page-sub' style='font-size:1.05rem;color:#2F6DB5;font-weight:600;margin-top:-0.8rem'>"
            "Intelligent Billing Operations</div>", unsafe_allow_html=True)

st.markdown(
    "<div class='note'>"
    "<b>Hi, I'm Vivek.</b> Version 1 of this app showed where the money is: what has been billed, collected and "
    "is still owed. Version 2 goes one step earlier, to the billing requests themselves. It shows how damage "
    "recovery, pole attachment, customer-requested work and connection requests could be checked on arrival, "
    "followed up automatically and matched to their invoices, so the team spends its time on exceptions, "
    "not on retyping and chasing."
    "<div class='note-sign'>Vivek Kumar · Computer Science (Co-op), Algoma University</div></div>",
    unsafe_allow_html=True)

b1, b2, _ = st.columns([1.3, 1.2, 3])
if b1.button("Explore Interactive Demo", type="primary", icon=":material/play_circle:", width="stretch"):
    st.switch_page("views/guided_demo.py")
if b2.button("Open AI Assistant", icon=":material/forum:", width="stretch"):
    st.switch_page("views/assistant.py")

st.subheader("At a glance")
c = st.columns(5)
ui.kpi(c[0], "Total billed", rc.money(m.billed), f"{len(m.inv):,} invoices")
ui.kpi(c[1], "Collection rate", f"{m.collection_rate:.1%}", f"{rc.money(m.collected)} collected")
ui.kpi(c[2], "Overdue", rc.money(m.overdue_amt), f"{rc.money(m.over_90)} over 90 days", "bad")
ui.kpi(c[3], "Requests on hold", f"{int(counts.get('Needs information', 0))}", "Missing information")
ui.kpi(c[4], "Awaiting approval", f"{int(counts.get('Awaiting approval', 0))}", "Over the approval limit")

left, right = st.columns([1.15, 1])
with left:
    st.subheader("Where to focus")
    slow = m.cycle_by_cat
    others = slow.drop(slow.index[-1]).mean()
    st.markdown(
        f"1. **Collections:** {rc.money(m.by_category['OverdueAR'].iloc[0])} overdue in "
        f"{m.by_category.index[0]}; {m.over_90 / m.outstanding:.0%} of all outstanding is over 90 days.\n"
        f"2. **Billing speed:** {slow.index[-1]} takes {slow.iloc[-1]:.0f} days to invoice, against about "
        f"{others:.0f} for other categories.\n"
        f"3. **Request queue:** {int(counts.get('Needs information', 0))} on hold, "
        f"{int(counts.get('Awaiting approval', 0))} waiting for a supervisor, {exceptions} invoice "
        f"{'mismatch' if exceptions == 1 else 'mismatches'}.")
    ui.ask_assistant("Home", "Give me today's briefing across receivables and the billing queue.",
                     label="Ask for today's briefing")
with right:
    st.subheader("Two-minute demo")
    for title, text in [
        ("A. A complete request", "Checked in seconds and ready to bill."),
        ("B. Missing information", "Held, followed up, corrected and approved."),
        ("C. A billing mismatch", "A wrong invoice is caught before it is marked billed."),
    ]:
        with st.container(border=True):
            st.markdown(f"**{title}**  \n<span style='color:#64748B;font-size:0.9rem'>{text}</span>",
                        unsafe_allow_html=True)
    if st.button("Start the guided demo", icon=":material/arrow_forward:"):
        st.switch_page("views/guided_demo.py")
ui.footer()
