"""Business Case: a one-page case for a small pilot."""
import streamlit as st

from core import receivables as rc
from views import common as ui

m = ui.metrics(rc.Filters())
slow = m.cycle_by_cat
others = slow.drop(rc.SLOW_CATEGORY).mean()
damage_overdue = m.by_category.loc[rc.SLOW_CATEGORY, "OverdueAR"]

ui.header("Business case", "A proposal for a small, low-risk pilot. Independent work based on synthetic data.")

st.subheader("Problem")
st.markdown(
    "Billing requests arrive from several teams by email and spreadsheet, in different formats. Each one is checked "
    "by hand, typed into a tracker and then into the billing system, and chased by email when something is "
    "missing. That work is slow, repetitive and easy to get wrong.")

st.subheader("What the data suggests")
st.markdown(
    f"- In the synthetic dataset, {rc.SLOW_CATEGORY} takes **{slow[rc.SLOW_CATEGORY]:.0f} days** from completed work "
    f"to invoice, against about **{others:.0f} days** for other categories.\n"
    f"- That category also holds the largest overdue balance, **{rc.money(damage_overdue)}**.\n"
    f"- **{m.over_90 / m.outstanding:.0%}** of the outstanding balance is more than 90 days past due "
    f"({rc.money(m.over_90)} of {rc.money(m.outstanding)}).\n\n"
    "A likely cause is that this category needs the most supporting information (incident date, claim number, "
    "documents), so incomplete requests go back and forth. This should be confirmed with the team before any change.")

st.subheader("Proposed improvement")
st.markdown(
    "1. **One intake** for forms, spreadsheets and emails, with the required fields set by billing category.\n"
    "2. **Automatic checks** on arrival (16 rules), so problems are found before billing, not after.\n"
    "3. **Follow-up drafted for the analyst**, asking only for what is missing. A person reviews and sends it.\n"
    "4. **Billing batches with a control total**, and every returned invoice **matched to its request** before it "
    "is marked billed.\n"
    "5. **An assistant** that answers questions from the calculated figures and shows its evidence.")

st.subheader("Controls")
st.markdown(
    "- Requests over an approval limit need a supervisor who did not log them; changing the amount, customer or "
    "category clears the approval.\n"
    "- Status can only move in allowed steps, and every change is recorded with who and when.\n"
    "- Nothing is marked billed until the invoice matches the request.\n"
    "- The AI cannot approve, send, bill or change anything. People review everything it drafts.")

st.subheader("Pilot")
st.markdown(
    "- **Scope:** one billing category (third-party damage recovery) and one or two submitting teams.\n"
    "- **Length:** six to eight weeks, run alongside the current process.\n"
    "- **No system integration:** the pilot works from exported files, so there is no risk to the billing system.\n"
    "- **Review:** compare against a baseline measured in the two weeks before the pilot.")

st.subheader("Success measures")
st.markdown(
    "| Measure | How it is measured |\n| --- | --- |\n"
    "| Complete first time | Share of requests with nothing missing on arrival |\n"
    "| Days to invoice | Work completed to invoice date, for the pilot category |\n"
    "| Follow-ups per request | Emails needed before a request can be billed |\n"
    "| Errors caught before the customer | Mismatches found at reconciliation |\n"
    "| Analyst time per request | Short time study before and during the pilot |\n\n"
    "Targets would be set after the baseline is measured. No savings are assumed in advance.")

st.subheader("Assumptions and limits")
st.markdown(
    "- All figures here come from a synthetic dataset, not company data.\n"
    "- The approval limit, rate card and rules are illustrative and would follow the team's own policy.\n"
    "- Any AI use would need the organization's approval and approved tools.")

st.subheader("How it could run on Microsoft Power Platform (proposed)")
st.markdown(
    "| In this prototype | Proposed equivalent |\n| --- | --- |\n"
    "| Request intake | Microsoft Forms or Power Apps |\n"
    "| Workflow tracker | SharePoint list or Dataverse table |\n"
    "| Checks and follow-up drafts | Power Automate flow creating Outlook drafts |\n"
    "| Approvals | Power Automate approvals |\n"
    "| Billing file | Excel export in the billing system's upload layout |\n"
    "| Reports and insights | Power BI |\n"
    "| Assistant | An approved assistant, such as Copilot Studio, on the same data |\n\n"
    "This mapping is a proposal. It has not been built or tested on Power Platform.")
ui.footer()
