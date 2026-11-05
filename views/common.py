"""Shared layout, styling, data access and per-visitor state."""
from __future__ import annotations

import html
from datetime import datetime
from typing import Callable, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai import guard, providers
from core import receivables as rc
from workflow import sample_data, store

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Toronto")
except Exception:  # tzdata missing
    TZ = None

# Palette: deep ink and teal on warm neutrals. Status colours are always paired with an icon and a word.
INK = "#12201C"
NAVY = "#134E4A"        # dark teal: headline series
BLUE = "#0E7C66"        # primary teal
LIGHT_BLUE = "#9DD5C6"  # light teal
GREY = "#7A7F78"
RED = "#B42318"
GREEN = "#15803D"
AMBER = "#C2620A"
AGING_COLOURS = ["#C6E7DD", "#7CC4B0", "#0E7C66", "#D97706", "#B42318"]
FILTER_KEYS = ["flt_regions", "flt_categories", "flt_ctypes"]
ROLES = [store.ANALYST, store.SUPERVISOR]

# Line icons (24px grid, drawn with the current text colour).
_ICON_PATHS = {
    "receipt": '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/>'
               '<path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 17.5v-11"/>',
    "trend": '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
    "wallet": '<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/>'
              '<path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>'
             '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    "hold": '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/>'
            '<line x1="12" x2="12.01" y1="16" y2="16"/>',
    "check": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    "x": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "inbox": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 '
             '2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "approve": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
               '<polyline points="16 11 18 13 22 9"/>',
    "batch": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9'
             'a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/>'
             '<path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "ban": '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    "file": '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>'
            '<polyline points="14 2 14 8 20 8"/><line x1="16" x2="8" y1="13" y2="13"/>'
            '<line x1="16" x2="8" y1="17" y2="17"/>',
    "scale": '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/>'
             '<path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/>'
             '<path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
    "refund": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "case": '<rect width="20" height="14" x="2" y="7" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
    "sigma": '<path d="M18 7V4H6l6 8-6 8h12v-3"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 '
              '4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>'
              '<path d="m9 12 2 2 4-4"/>',
    "mail": '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "dot": '<circle cx="12" cy="12" r="4" fill="currentColor"/>',
}


def icon(name: str, size: int = 18) -> str:
    """An inline line icon. Decorative: the label next to it always carries the meaning."""
    return (f"<svg class='ico' width='{size}' height='{size}' viewBox='0 0 24 24' fill='none' stroke='currentColor' "
            f"stroke-width='2' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>"
            f"{_ICON_PATHS.get(name, _ICON_PATHS['dot'])}</svg>")


CSS = """
<style>
:root {--ink:#12201C; --text:#1E2A26; --muted:#6B716B; --line:#E6E3DC; --surface:#FFFFFF; --canvas:#F7F6F2;
       --teal:#0E7C66; --teal-dark:#134E4A; --teal-tint:#E7F4EF;
       --red:#B42318; --red-tint:#FDECEA; --amber:#B4570A; --amber-tint:#FDF1E3;
       --green:#15803D; --green-tint:#E8F5EC; --blue:#2856A6; --blue-tint:#EAF0FB; --grey-tint:#F1F0EC;}
.block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1360px;}
h1 {font-size: 1.65rem !important; font-weight: 700 !important; color: var(--ink); letter-spacing: -0.01em;}
h3 {font-size: 1.02rem !important; font-weight: 650 !important; color: var(--ink); padding-top: 1.2rem !important;}
section[data-testid="stSidebar"] {background: var(--surface); border-right: 1px solid var(--line);}
.page-sub {color: var(--muted); font-size: 0.92rem; margin-top: -0.6rem; margin-bottom: 1.3rem;}
.tagline {color: var(--teal); font-size: 1.05rem; font-weight: 600; margin-top: -0.8rem; margin-bottom: 1.2rem;}
.ico {vertical-align: -0.18em; flex: none;}

.kpi {background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px;
      min-height: 124px; display: flex; flex-direction: column; box-shadow: 0 1px 2px rgba(18,32,28,0.04);}
.kpi-top {display: flex; align-items: flex-start; justify-content: space-between; gap: 8px;}
.kpi-top .kpi-label {padding-top: 2px;}
.kpi-label {color: var(--muted); font-size: 0.74rem; font-weight: 600; text-transform: uppercase;
            letter-spacing: 0.05em;}
.kpi-chip {display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px;
           border-radius: 9px; background: var(--teal-tint); color: var(--teal);}
.kpi-chip.bad {background: var(--red-tint); color: var(--red);}
.kpi-chip.warn {background: var(--amber-tint); color: var(--amber);}
.kpi-chip.good {background: var(--green-tint); color: var(--green);}
.kpi-chip.info {background: var(--blue-tint); color: var(--blue);}
.kpi-value {color: var(--ink); font-size: 1.6rem; font-weight: 700; margin-top: auto; padding-top: 6px;
            font-variant-numeric: tabular-nums; letter-spacing: -0.01em;}
.kpi-note {color: var(--muted); font-size: 0.8rem; margin-top: 2px;}
.kpi-note.bad {color: var(--red);}
.kpi-note.good {color: var(--green);}
.kpi-note.warn {color: var(--amber);}

.status-tile {background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px;
              border-top: 3px solid var(--c); min-height: 100px; display: flex; flex-direction: column;
              box-shadow: 0 1px 2px rgba(18,32,28,0.04);}
.status-tile .st-head {display: flex; align-items: flex-start; gap: 7px; color: var(--c); font-size: 0.78rem;
                       font-weight: 650; line-height: 1.25; min-height: 2.5em;}
.status-tile .st-count {color: var(--ink); font-size: 1.55rem; font-weight: 700; margin-top: auto; padding-top: 6px;
                        font-variant-numeric: tabular-nums;}
.status-tile.zero .st-count {color: #A6A9A3;}

.panel-note {color: var(--muted); font-size: 0.83rem; margin-top: -0.5rem; margin-bottom: 0.4rem;}
.insight {background: var(--teal-tint); border-left: 3px solid var(--teal); padding: 10px 14px; border-radius: 6px;
          color: var(--text); font-size: 0.9rem; margin: 1.1rem 0 0.9rem 0;}
.badge {display: inline-flex; align-items: center; gap: 4px; padding: 2px 9px 2px 7px; border-radius: 999px;
        font-size: 0.78rem; font-weight: 600; border: 1px solid transparent; vertical-align: middle;
        white-space: nowrap;}
.badge.ready {background: var(--green-tint); color: var(--green); border-color: #BFE0C9;}
.badge.warn {background: var(--amber-tint); color: var(--amber); border-color: #F1D2AE;}
.badge.fix {background: var(--red-tint); color: var(--red); border-color: #F2C4BE;}
.badge.info {background: var(--blue-tint); color: var(--blue); border-color: #C9D7F2;}
.badge.muted {background: var(--grey-tint); color: #55595A; border-color: var(--line);}
.demo-flag {display: flex; align-items: center; gap: 6px; background: var(--teal-tint); color: var(--teal-dark);
            border: 1px solid #C5E3D9; border-radius: 8px; padding: 6px 10px; font-size: 0.8rem;
            margin: 0.2rem 0 0.6rem 0;}
.side-foot {color: var(--muted); font-size: 0.78rem; margin-top: 1.2rem; line-height: 1.6;}
.side-foot a {color: var(--teal); text-decoration: none; font-weight: 600;}
.note {background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--teal);
       border-radius: 12px; padding: 16px 20px; color: var(--text); font-size: 0.98rem; line-height: 1.6;
       margin: 0.4rem 0 1.1rem 0; box-shadow: 0 1px 2px rgba(18,32,28,0.04);}
.note-sign {color: var(--muted); font-size: 0.85rem; margin-top: 8px;}
.scenario {display: flex; gap: 12px; align-items: flex-start; background: var(--surface); border: 1px solid var(--line);
           border-radius: 12px; padding: 12px 14px; margin-bottom: 10px;}
.scenario .kpi-chip {flex: none;}
.scenario b {color: var(--ink);}
.scenario span {color: var(--muted); font-size: 0.9rem;}
.exception {display: flex; gap: 12px; align-items: flex-start; background: var(--surface);
             border: 1px solid #F2C4BE; border-left: 4px solid var(--red); border-radius: 12px; padding: 12px 16px;
             margin: 0.4rem 0 0.8rem 0;}
.exception b {color: var(--ink);}
.exception .ex-body {color: var(--text); font-size: 0.92rem; margin-top: 2px;}
.footer {color: var(--muted); font-size: 0.76rem; margin-top: 2.5rem; border-top: 1px solid var(--line);
         padding-top: 0.8rem;}
div[data-testid="stChatMessage"] {background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
                                  padding: 12px 16px; margin-bottom: 0.6rem;}
[data-testid="stChatMessageAvatarUser"] {background: var(--grey-tint) !important; color: var(--ink) !important;}
[data-testid="stChatMessageAvatarAssistant"] {background: var(--teal) !important; color: #FFFFFF !important;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 12px;}
div[data-testid="stPlotlyChart"] {background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
                                  padding: 8px 6px 4px 6px; overflow: hidden;}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"][aria-current="page"] {background: var(--teal-tint);}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"][aria-current="page"] span {color: var(--teal-dark) !important;}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"]:hover {background: #F1F0EC;}
div[data-testid="stProgress"] > div > div {background-color: var(--line);}
</style>
"""

STATUS_BADGE = {
    "Received": "info", "Needs information": "fix", "Awaiting approval": "warn", "Ready to bill": "ready",
    "In billing batch": "info", "Billed": "ready", "Cancelled": "muted",
    "Must fix": "fix", "Needs approval": "warn", "Warning": "warn", "Ready": "ready",
    "Matched": "ready", "Amount differs": "fix", "No invoice found": "fix", "Not in this batch": "warn",
}
STATUS_ICON = {
    "Received": "inbox", "Needs information": "hold", "Awaiting approval": "approve", "Ready to bill": "check",
    "In billing batch": "batch", "Billed": "receipt", "Cancelled": "ban", "Must fix": "x", "Needs approval": "approve",
    "Warning": "alert", "Ready": "check", "Matched": "check", "Amount differs": "x", "No invoice found": "x",
    "Not in this batch": "alert",
}
TONE_COLOUR = {"fix": "var(--red)", "warn": "var(--amber)", "ready": "var(--green)", "info": "var(--blue)",
               "muted": "#7A7F78"}


def style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def badge(text: str) -> str:
    """A status label with a word and an icon, never colour alone."""
    return (f"<span class='badge {STATUS_BADGE.get(text, 'muted')}'>{icon(STATUS_ICON.get(text, 'dot'), 13)}"
            f"{text}</span>")


def _safe(text: str) -> str:
    """Escape text for HTML, with $ as an entity so Markdown never reads it as maths."""
    return html.escape(str(text)).replace("$", "&#36;")


def exception_card(title: str, body: str) -> None:
    """A control catching a problem, shown as a finding rather than as an app error."""
    st.markdown(f"<div class='exception'><span class='kpi-chip bad'>{icon('shield', 17)}</span>"
                f"<div><b>{_safe(title)}</b><div class='ex-body'>{_safe(body)}</div></div></div>",
                unsafe_allow_html=True)


def status_tile(col, status: str, count: int) -> None:
    """A count tile for one workflow status: colour, icon and word together."""
    colour = TONE_COLOUR[STATUS_BADGE.get(status, "muted")]
    col.markdown(f"<div class='status-tile{' zero' if not count else ''}' style='--c:{colour}'>"
                 f"<div class='st-head'>{icon(STATUS_ICON.get(status, 'dot'), 16)}<span>{status}</span></div>"
                 f"<div class='st-count'>{count}</div></div>", unsafe_allow_html=True)


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


@st.cache_data(ttl=6 * 3600, max_entries=300, show_spinner=False)
def _cached_answer(system: str, history: tuple) -> str:
    provider = ai_provider()
    if provider is None:
        raise providers.AIError("The assistant is offline.")
    return providers.answer(provider, system, [{"role": r, "content": c} for r, c in history])


def ai_answer(system: str, messages: List[dict]) -> str:
    """A complete, checked answer. The same question on the same figures is answered once and reused for six
    hours, which keeps the free AI quota for new questions. Failures are not cached. Raises AIError."""
    secrets = [providers.setting("GEMINI_API_KEY"), providers.setting("ANTHROPIC_API_KEY")]
    text = _cached_answer(system, tuple((m["role"], m["content"]) for m in messages))
    return "".join(guard.limit_stream([text], secrets))


def type_out(text: str):
    """Show a finished answer word by word, so it reads like a reply rather than appearing all at once."""
    import time
    for word in esc(text).split(" "):
        yield word + " "
        time.sleep(0.012)


# ---------------------------------------------------------------- page furniture
def sidebar() -> None:
    with st.sidebar:
        st.session_state["_filter_slot"] = st.container()
        st.markdown(f"<div class='demo-flag'>{icon('shield', 15)}<span><b>Demo</b> · synthetic data</span></div>",
                    unsafe_allow_html=True)
        st.radio("Role (simulated)", ROLES, key="role", horizontal=True,
                 help="Switch to Supervisor to approve requests. There is no sign-in in this demo.")
        st.button("Reset demo", icon=":material/restart_alt:", width="stretch", on_click=reset_demo)
        st.markdown("<div class='side-foot'>Built by Vivek Kumar<br>"
                    "<a href='https://www.linkedin.com/in/vivek-kumar-812211247' target='_blank'>LinkedIn</a> · "
                    "<a href='https://github.com/DevModeVivek/receivables-billing-assistant' target='_blank'>GitHub</a>"
                    "</div>", unsafe_allow_html=True)


def header(title: str, subtitle: str, reporting: bool = False) -> None:
    st.title(title)
    extra = f" &nbsp;·&nbsp; As of {rc.AS_OF_LABEL} &nbsp;·&nbsp; {current_filters().text()}" if reporting else ""
    st.markdown(f"<div class='page-sub'>{subtitle}{extra}</div>", unsafe_allow_html=True)


def footer(text: Optional[str] = None) -> None:
    text = text or "Synthetic demo data · Built by Vivek Kumar"
    st.markdown(f"<div class='footer'>{text}</div>", unsafe_allow_html=True)


def kpi(col, label: str, value: str, note: str = "", tone: str = "", help_text: str = "", icon_name: str = "",
        chip: str = "") -> None:
    """A figure tile. `tone` colours the note (bad, good, warn); `chip` colours the icon (defaults to tone)."""
    title = f" title='{help_text}'" if help_text else ""
    chip_html = f"<span class='kpi-chip {chip or tone}'>{icon(icon_name, 17)}</span>" if icon_name else ""
    col.markdown(
        f"<div class='kpi'{title}><div class='kpi-top'><div class='kpi-label'>{label}</div>{chip_html}</div>"
        f"<div class='kpi-value'>{value}</div><div class='kpi-note {tone}'>{note}</div></div>",
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
        font=dict(family="Source Sans Pro, Segoe UI, sans-serif", size=12, color="#1E2A26"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        hoverlabel=dict(bgcolor="white"), bargap=0.35,
    )
    fig.update_xaxes(showgrid=False, title=None, linecolor="#E6E3DC", ticks="")
    fig.update_yaxes(gridcolor="#EFEDE7", showgrid=True, title=None, linecolor="#E6E3DC", ticks="")
    fig.update_traces(selector=dict(type="bar"), cliponaxis=False)
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False})


def hbar(series: pd.Series, colour: str, fmt: Callable = rc.money, colours: Optional[List[str]] = None):
    fig = go.Figure(go.Bar(x=series.values, y=series.index, orientation="h", marker_color=colours or colour,
                           text=[fmt(v) for v in series.values], textposition="outside",
                           hovertemplate="%{y}: %{text}<extra></extra>"))
    fig.update_xaxes(showgrid=True, gridcolor="#EFEDE7")
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
