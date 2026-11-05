"""Home: what this is, the key figures, today's priorities and the guided demo."""
import streamlit as st

from core import receivables as rc
from views import common as ui
from workflow import store

m = ui.metrics(rc.Filters())  # headline figures always use the full portfolio
conn = ui.workspace()
reqs = store.table(conn, "SELECT status, followups_sent, exception FROM requests")
counts = reqs["status"].value_counts()
to_follow = int(((reqs["status"] == "Needs information") & (reqs["followups_sent"].fillna(0) == 0)).sum())
exceptions = int(reqs["exception"].notna().sum())

st.title("Receivables & Billing Insights")
st.markdown("<div class='page-sub' style='font-size:1.05rem;color:#2F6DB5;font-weight:600;margin-top:-0.8rem'>"
            "Intelligent Billing Operations</div>", unsafe_allow_html=True)
st.markdown(
    "A working prototype for a billing and receivables team. It shows where money is owed, checks incoming "
    "billing requests before they are billed, catches errors when invoices come back, and includes an assistant "
    "that answers questions from the calculated figures.")
st.info("All customers, requests and amounts are synthetic. This is an independent portfolio project, "
        "not a system used by any company.", icon=":material/info:")

b1, b2, _ = st.columns([1.3, 1.2, 3])
if b1.button("Explore Interactive Demo", type="primary", icon=":material/play_circle:", width="stretch"):
    st.switch_page("views/guided_demo.py")
if b2.button("Open AI Assistant", icon=":material/forum:", width="stretch"):
    st.switch_page("views/assistant.py")

st.subheader("Key figures")
st.markdown(f"<div class='panel-note'>Receivables as of {rc.AS_OF_LABEL} (fixed report) · billing queue from the live "
            "demo workspace</div>", unsafe_allow_html=True)
c = st.columns(5)
ui.kpi(c[0], "Total billed", rc.money(m.billed), f"{len(m.inv):,} invoices")
ui.kpi(c[1], "Collection rate", f"{m.collection_rate:.1%}", f"{rc.money(m.collected)} collected")
ui.kpi(c[2], "Overdue", rc.money(m.overdue_amt), f"{rc.money(m.over_90)} over 90 days", "bad")
ui.kpi(c[3], "Requests on hold", f"{int(counts.get('Needs information', 0))}", "Missing or wrong information")
ui.kpi(c[4], "Ready to bill", f"{int(counts.get('Ready to bill', 0))}", "Checked and approved")

left, right = st.columns([1.15, 1])
with left:
    st.subheader("Operational priorities")
    st.markdown("<div class='panel-note'>Worked out by the app from the figures above; no AI involved</div>",
                unsafe_allow_html=True)
    slow = m.cycle_by_cat
    others = slow.drop(slow.index[-1]).mean()
    st.markdown(
        f"1. **Collections:** {rc.money(m.by_category['OverdueAR'].iloc[0])} of overdue balance is in "
        f"{m.by_category.index[0]}, and {m.over_90 / m.outstanding:.0%} of everything outstanding is over 90 days.\n"
        f"2. **Billing speed:** {slow.index[-1]} takes {slow.iloc[-1]:.0f} days to invoice, against about "
        f"{others:.0f} for other categories.\n"
        f"3. **Billing queue:** {int(counts.get('Needs information', 0))} requests on hold for missing information "
        f"({to_follow} still need a first follow-up), {int(counts.get('Awaiting approval', 0))} waiting for a "
        f"supervisor, and {exceptions} invoice {'mismatch' if exceptions == 1 else 'mismatches'} to resolve.")
    ui.ask_assistant("Home", "Give me today's briefing across receivables and the billing queue.",
                     label="Ask the assistant for today's briefing")
with right:
    st.subheader("Try the three demo scenarios")
    st.markdown("<div class='panel-note'>About two minutes. Each step runs the real checks.</div>",
                unsafe_allow_html=True)
    for title, text in [
        ("A. A complete request", "Checked in seconds and ready to bill with no manual review."),
        ("B. Missing information", "Held at intake, a follow-up drafted, corrected, re-checked and approved."),
        ("C. A billing mismatch", "An invoice keyed wrongly is caught at reconciliation and not marked billed."),
    ]:
        with st.container(border=True):
            st.markdown(f"**{title}**  \n<span style='color:#64748B;font-size:0.9rem'>{text}</span>",
                        unsafe_allow_html=True)
    if st.button("Start the guided demo", icon=":material/arrow_forward:"):
        st.switch_page("views/guided_demo.py")

st.subheader("What this would change for a billing team")
v = st.columns(3)
for col, (title, text) in zip(v, [
    ("Less re-keying and chasing", "Requests are checked on arrival against 16 rules, and the follow-up email is "
                                   "drafted with exactly what is missing."),
    ("Errors caught before customers see them", "Batches carry a control total, and every invoice is matched back "
                                                "to its request before it is marked billed."),
    ("Answers in plain English", "Managers ask questions and get answers built only from calculated figures, "
                                 "with the evidence shown."),
]):
    with col.container(border=True):
        st.markdown(f"**{title}**  \n<span style='color:#475569;font-size:0.9rem'>{text}</span>",
                    unsafe_allow_html=True)
st.caption("No savings figures are claimed. The Business Case page proposes how a pilot would measure them.")
ui.footer()
