"""Shared layout, styling, data access and per-visitor state."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai import providers
from core import receivables as rc
from workflow import sample_data, store

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Toronto")
except Exception:  # tzdata missing
    TZ = None

NAVY = "#14365D"
BLUE = "#2F6DB5"
LIGHT_BLUE = "#A9C4E6"
GREY = "#64748B"
RED = "#B03A2E"
GREEN = "#2E7D4F"
AMBER = "#C9772B"
AGING_COLOURS = ["#A9C4E6", "#6E9BD1", "#2F6DB5", "#C9772B", "#B03A2E"]
FILTER_KEYS = ["flt_regions", "flt_categories", "flt_ctypes"]
ROLES = [store.ANALYST, store.SUPERVISOR]

CSS = """
<style>
.block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1360px;}
h1 {font-size: 1.6rem !important; font-weight: 600 !important; color: #14365D;}
h3 {font-size: 1.02rem !important; font-weight: 600 !important; color: #1F2937; padding-top: 1.2rem !important;}
section[data-testid="stSidebar"] {background: #F1F5F9; border-right: 1px solid #E2E8F0;}
.page-sub {color: #64748B; font-size: 0.9rem; margin-top: -0.6rem; margin-bottom: 1.3rem;}
.kpi {background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 14px 16px; min-height: 108px;}
.kpi-label {color: #64748B; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em;}
.kpi-value {color: #14365D; font-size: 1.55rem; font-weight: 600; margin-top: 6px;}
.kpi-note {color: #64748B; font-size: 0.8rem; margin-top: 4px;}
.kpi-note.bad {color: #B03A2E;}
.kpi-note.good {color: #2E7D4F;}
.panel-note {color: #64748B; font-size: 0.83rem; margin-top: -0.5rem; margin-bottom: 0.4rem;}
.insight {background: #F1F6FC; border-left: 3px solid #2F6DB5; padding: 10px 14px; border-radius: 4px;
          color: #1F2937; font-size: 0.9rem; margin: 1.1rem 0 0.9rem 0;}
.badge {display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: 0.78rem; font-weight: 600;
        border: 1px solid transparent;}
.badge.ready {background: #E8F3EC; color: #2E7D4F; border-color: #BFDCC9;}
.badge.warn {background: #FBF0E6; color: #9A5A1F; border-color: #EBCDAE;}
.badge.fix {background: #F8E9E7; color: #B03A2E; border-color: #E6C1BC;}
.badge.info {background: #EAF1FA; color: #14365D; border-color: #C9DAF0;}
.badge.muted {background: #F1F5F9; color: #475569; border-color: #E2E8F0;}
.demo-flag {background: #EAF1FA; color: #14365D; border: 1px solid #C9DAF0; border-radius: 6px;
            padding: 6px 10px; font-size: 0.8rem; margin: 0.2rem 0 0.6rem 0;}
.side-foot {color: #64748B; font-size: 0.75rem; margin-top: 1.2rem; line-height: 1.5;}
.footer {color: #64748B; font-size: 0.76rem; margin-top: 2.5rem; border-top: 1px solid #E2E8F0; padding-top: 0.8rem;}
div[data-testid="stChatMessage"] {background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px;
                                  padding: 12px 16px; margin-bottom: 0.6rem;}
[data-testid="stChatMessageAvatarUser"] {background: #E2E8F0 !important; color: #14365D !important;}
[data-testid="stChatMessageAvatarAssistant"] {background: #14365D !important; color: #FFFFFF !important;}
.count-card .kpi-label {font-size: 0.68rem;}
div[data-testid="stProgress"] > div > div {background-color: #E2E8F0;}
</style>
"""

STATUS_BADGE = {
    "Received": "info", "Needs information": "fix", "Awaiting approval": "warn", "Ready to bill": "ready",
    "In billing batch": "info", "Billed": "ready", "Cancelled": "muted",
    "Must fix": "fix", "Needs approval": "warn", "Warning": "warn", "Ready": "ready",
    "Matched": "ready", "Amount differs": "fix", "No invoice found": "fix", "Not in this batch": "warn",
}
STATUS_ICON = {
    "Received": "●", "Needs information": "✕", "Awaiting approval": "◐", "Ready to bill": "✓",
    "In billing batch": "→", "Billed": "✓", "Cancelled": "–", "Must fix": "✕", "Needs approval": "◐",
    "Warning": "!", "Ready": "✓", "Matched": "✓", "Amount differs": "✕", "No invoice found": "✕",
    "Not in this batch": "!",
}


def style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def badge(text: str) -> str:
    """A status label with a word and a symbol, never colour alone."""
    return (f"<span class='badge {STATUS_BADGE.get(text, 'muted')}'>{STATUS_ICON.get(text, '')} "
            f"{text}</span>")


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None) if TZ else datetime.now()


# ---------------------------------------------------------------- reporting data (fixed snapshot)
@st.cache_data(show_spinner=False)
def frames() -> rc.Frames:
    return rc.load_data()


def keep_filters() -> None:
    """Keep the filter choices when the visitor moves to a page that does not show them."""
    for k in FILTER_KEYS:
        if k in st.session_state:
            st.session_state[k] = st.session_state[k]


def current_filters() -> rc.Filters:
    return rc.Filters(list(st.session_state.get("flt_regions", [])), list(st.session_state.get("flt_categories", [])),
                      list(st.session_state.get("flt_ctypes", [])))


def filter_controls() -> rc.Filters:
    f = frames()
    slot = st.session_state.get("_filter_slot") or st.sidebar
    with slot:
        st.caption("REPORT FILTERS")
        st.multiselect("Region", sorted(f.inv["Region"].unique()), placeholder="All regions", key="flt_regions")
        st.multiselect("Billing category", sorted(f.inv["BillingCategory"].unique()), placeholder="All categories",
                       key="flt_categories")
        st.multiselect("Customer type", sorted(f.inv["CustomerType"].unique()), placeholder="All types",
                       key="flt_ctypes")
    return current_filters()


def metrics(filters: Optional[rc.Filters] = None) -> rc.Metrics:
    return rc.compute(frames(), filters or current_filters())


# ---------------------------------------------------------------- workflow workspace (per visitor)
@st.cache_data(show_spinner=False)
def customers() -> dict:
    return sample_data.customer_lookup()


def workspace():
    """This visitor's own in-memory tracker, created on first use."""
    if "ws_conn" not in st.session_state:
        with st.spinner("Preparing your demo workspace..."):
            conn = store.connect(":memory:")
            sample_data.build_demo(conn, now())
            st.session_state["ws_conn"] = conn
    return st.session_state["ws_conn"]


def role() -> str:
    return st.session_state.get("role", store.ANALYST)


def reset_demo() -> None:
    conn = st.session_state.pop("ws_conn", None)
    if conn is not None:
        conn.close()
    keep = {"role"}
    for k in list(st.session_state.keys()):
        if k not in keep and not k.startswith("_"):
            del st.session_state[k]
    st.session_state["role"] = store.ANALYST


@st.cache_resource(ttl=300, show_spinner=False)
def ai_provider():
    return providers.connect()


def ai_status() -> str:
    p = ai_provider()
    if p is None:
        return "AI assistant: not configured"
    return f"AI assistant: {p.name}"


# ---------------------------------------------------------------- page furniture
def sidebar() -> None:
    with st.sidebar:
        st.session_state["_filter_slot"] = st.container()
        st.markdown("<div class='demo-flag'><b>Demo mode</b> · all data is synthetic</div>", unsafe_allow_html=True)
        st.radio("Acting as (simulated role)", ROLES, key="role", horizontal=True,
                 help="A role switch for the demo only. There are no real users or sign-in.")
        st.button("Reset demo", icon=":material/restart_alt:", width="stretch", on_click=reset_demo,
                  help="Start again with fresh demo data. Your changes are cleared.")
        st.caption(ai_status())
        st.markdown("<div class='side-foot'>Independent portfolio project by Vivek Kumar.<br>"
                    "Not affiliated with or endorsed by any utility.<br>Version 2.0</div>", unsafe_allow_html=True)


def header(title: str, subtitle: str, reporting: bool = False) -> None:
    st.title(title)
    extra = f" &nbsp;·&nbsp; As of {rc.AS_OF_LABEL} &nbsp;·&nbsp; {current_filters().text()}" if reporting else ""
    st.markdown(f"<div class='page-sub'>{subtitle}{extra}</div>", unsafe_allow_html=True)


def footer(text: Optional[str] = None) -> None:
    p = ai_provider()
    if text is None:
        if p is None:
            ai_line = "The AI assistant is not configured in this copy"
        elif p.hosted:
            ai_line = f"Assistant questions, which contain only fictional demo data, are sent to {p.name}"
        else:
            ai_line = "The assistant runs on a local model, so questions stay on this computer"
        text = f"All data is synthetic · Figures and checks calculated in Python · {ai_line}"
    st.markdown(f"<div class='footer'>{text}</div>", unsafe_allow_html=True)


def kpi(col, label: str, value: str, note: str = "", tone: str = "", help_text: str = "") -> None:
    title = f" title='{help_text}'" if help_text else ""
    col.markdown(
        f"<div class='kpi'{title}><div class='kpi-label'>{label}</div><div class='kpi-value'>{value}</div>"
        f"<div class='kpi-note {tone}'>{note}</div></div>",
        unsafe_allow_html=True,
    )


def section(title: str, note: str) -> None:
    st.subheader(title)
    st.markdown(f"<div class='panel-note'>{note}</div>", unsafe_allow_html=True)


def insight(text: str) -> None:
    st.markdown(f"<div class='insight'>{text}</div>", unsafe_allow_html=True)


def chart(fig, height: int = 320) -> None:
    fig.update_layout(
        template="simple_white", height=height, margin=dict(l=8, r=70, t=28, b=8),
        paper_bgcolor="white", plot_bgcolor="white",
        font=dict(family="Source Sans Pro, Segoe UI, sans-serif", size=12, color="#1F2937"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        hoverlabel=dict(bgcolor="white"), bargap=0.35,
    )
    fig.update_xaxes(showgrid=False, title=None, linecolor="#E2E8F0", ticks="")
    fig.update_yaxes(gridcolor="#EEF2F6", showgrid=True, title=None, linecolor="#E2E8F0", ticks="")
    fig.update_traces(selector=dict(type="bar"), cliponaxis=False)
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False})


def hbar(series: pd.Series, colour: str, fmt: Callable = rc.money, colours: Optional[List[str]] = None):
    fig = go.Figure(go.Bar(x=series.values, y=series.index, orientation="h", marker_color=colours or colour,
                           text=[fmt(v) for v in series.values], textposition="outside",
                           hovertemplate="%{y}: %{text}<extra></extra>"))
    fig.update_xaxes(showgrid=True, gridcolor="#EEF2F6")
    fig.update_yaxes(showgrid=False)
    return fig


def ask_assistant(page: str, question: Optional[str] = None, label: str = "Ask the assistant about this page") -> None:
    """A button that opens the assistant with this page's suggested questions (and optionally a question)."""
    if st.button(label, icon=":material/forum:", key=f"ask_{page}_{question or ''}"[:120]):
        st.session_state["assistant_from"] = page
        if question:
            st.session_state["assistant_pending"] = question
        st.switch_page("views/assistant.py")


def esc(text) -> str:
    """Escape dollar signs so Streamlit Markdown does not read them as maths."""
    return str(text).replace("$", "\\$")
