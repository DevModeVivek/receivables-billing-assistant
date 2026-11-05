"""Receivables & Billing Insights 2.0: Intelligent Billing Operations.

This file only sets up navigation and the shared sidebar. Each page lives in
views/, the Version 1 calculations in core/, the billing workflow in workflow/
and the assistant in ai/.

Run with:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="Receivables & Billing Insights", page_icon="assets/icon.svg", layout="wide",
                   initial_sidebar_state="auto")

from views import common  # noqa: E402  (set_page_config must run first)

common.style()
common.keep_filters()
st.logo("assets/logo.svg", size="large", icon_image="assets/icon.svg")


def page(path, title, icon, **kw):
    return st.Page(path, title=title, icon=f":material/{icon}:", **kw)


pages = {
    "": [
        page("views/home.py", "Home", "home", default=True),
        page("views/guided_demo.py", "Guided Demo", "play_circle"),
    ],
    "Workspace": [
        page("views/overview.py", "Executive Overview", "dashboard"),
        page("views/billing_ops.py", "Billing Operations", "receipt_long"),
        page("views/collections.py", "Collections", "account_balance_wallet"),
    ],
    "Operations": [
        page("views/intake.py", "Request Intake", "inbox"),
        page("views/tracker.py", "Workflow Tracker", "view_kanban"),
        page("views/quality.py", "Billing Quality", "fact_check"),
    ],
    "Intelligence": [
        page("views/assistant.py", "AI Assistant", "forum"),
        page("views/insights.py", "Process Insights", "insights"),
    ],
}

nav = st.navigation(pages, position="sidebar", expanded=True)
common.sidebar()
nav.run()
