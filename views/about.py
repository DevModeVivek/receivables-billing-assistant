"""About: what this project is, how it was built, how AI is used and its limits."""
import streamlit as st

from views import common as ui

provider = ui.ai_provider()
ui.header("About this project", "An independent portfolio project by Vivek Kumar")

st.markdown(
    "Receivables & Billing Insights is a prototype for a utility billing and receivables team. Version 1 analysed "
    "receivables and billing speed. Version 2 adds the billing request workflow around it: intake, checks, "
    "approvals, billing batches and reconciliation, with one assistant across both.")
st.markdown("It is not affiliated with, commissioned by or endorsed by any company. All data is synthetic.")

st.subheader("Version history")
st.markdown(
    "| Version | What it added |\n| --- | --- |\n"
    "| 1.0 | Receivables overview, billing operations, collections worklist and a local AI assistant (Ollama) "
    "on a synthetic dataset as of 30 Sep 2026 |\n"
    "| 2.0 | Grouped navigation and home page; request intake from form, spreadsheet or email; 16 rule checks; "
    "workflow tracker with enforced status steps; follow-up drafts; approvals; billing batches with control totals; "
    "reconciliation; process insights; guided demo; hosted or local assistant over reports and workflow |")

st.subheader("How AI is used")
st.markdown(
    "- **Python does the work.** Every figure, check, status and match is calculated by plain code and gives the "
    "same answer every time.\n"
    "- **The assistant explains.** It receives only calculated summaries (shown on its page), answers in plain "
    "English, separates observations from recommendations, and says when the data cannot answer a question.\n"
    "- **Free-text emails.** When an email does not follow the template, the AI suggests field values; every value is "
    "checked against the email text and anything not found is flagged for a person.\n"
    "- **It cannot act.** It does not send email, approve, bill or change any record.")

st.subheader("Privacy")
if provider is None:
    st.markdown("In this copy the AI assistant is not configured, so nothing is sent to any AI service.")
elif provider.hosted:
    st.markdown(f"This copy uses {provider.name}, a hosted AI service. Questions and the calculated demo summaries "
                "are sent to it. They contain only fictional data. On a free tier, the provider may use prompts to "
                "improve its products, so please do not type real personal or company information.")
else:
    st.markdown("This copy uses a local model, so questions and summaries stay on this computer.")
st.markdown("Each visitor gets a private, temporary copy of the demo data that is cleared when they leave or reset.")

st.subheader("Limits")
st.markdown(
    "- Synthetic data only; thresholds, rate card and rules are illustrative.\n"
    "- No real billing system (such as SAP) or email system is connected; files and drafts stand in for them.\n"
    "- The simulated role switch is for the demo; there is no sign-in.\n"
    "- On free hosting the app sleeps after a period without visitors and takes a moment to wake.")

st.subheader("Built with")
st.markdown("Python, Streamlit, pandas, Plotly and SQLite (in memory). Assistant: Google Gemini, Claude or Ollama.")
st.markdown("[GitHub](https://github.com/DevModeVivek/receivables-billing-assistant) · "
            "[LinkedIn](https://www.linkedin.com/in/vivek-kumar-812211247) · "
            "[Portfolio](https://vivekkumarportfolio.vercel.app)")
ui.footer()
