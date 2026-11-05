"""The running app: every page loads, reset works, visitors are isolated, and the guided demo works from a fresh
session. These use Streamlit's own test runner, with no AI configured (as on a host without Ollama)."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from ai import providers  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")
PAGES = ["views/home.py", "views/guided_demo.py", "views/overview.py", "views/billing_ops.py",
         "views/collections.py", "views/intake.py", "views/tracker.py", "views/quality.py", "views/assistant.py",
         "views/insights.py", "views/business_case.py", "views/about.py"]


@pytest.fixture(autouse=True)
def no_ai(monkeypatch):
    for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "AI_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(providers, "_try_ollama", lambda: None)
    import streamlit as st
    st.cache_resource.clear()


def start():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    return at


def click(at, key):
    at.button(key=key).click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_every_page_loads_without_ai():
    at = start()
    for page in PAGES:
        at.switch_page(page)
        at.run()
        assert not at.exception, (page, [e.value for e in at.exception])
    at.switch_page("views/assistant.py")
    at.run()
    assert any("not configured" in w.value for w in at.warning)


def test_filters_change_the_reports_and_persist_across_pages():
    at = start()
    at.switch_page("views/overview.py")
    at.run()
    at.multiselect(key="flt_regions").select("Northern")
    at.run()
    assert any("$14.62M" in m.value for m in at.markdown)
    at.switch_page("views/home.py")
    at.run()
    at.switch_page("views/billing_ops.py")
    at.run()
    assert at.session_state["flt_regions"] == ["Northern"]
    assert any("Northern" in m.value for m in at.markdown if "page-sub" in m.value)


def test_guided_demo_from_a_fresh_session():
    at = start()
    at.switch_page("views/guided_demo.py")
    at.run()
    for key in ["a_go", "b_go", "b_draft_go", "b_sent"]:
        click(at, key)
    at.text_input(key="b_claim").input("CLM-20931")
    at.checkbox(key="b_docs").check()
    at.run()
    click(at, "b_fix")
    click(at, "b_role")
    click(at, "b_approve")
    click(at, "c_go")
    click(at, "c_recon_go")
    assert any("not Billed" in e.value for e in at.error)
    click(at, "c_fix")
    assert any("Done." in s.value for s in at.success)


def test_reset_clears_the_visitor_workspace():
    at = start()
    at.switch_page("views/guided_demo.py")
    at.run()
    click(at, "a_go")
    conn = at.session_state["ws_conn"]
    before = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    at.sidebar.button[0].click()  # Reset demo
    at.run()
    assert not at.session_state["demo"]  # the demo starts again
    after = at.session_state["ws_conn"].execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    assert after == before - 1 and at.session_state["role"] == "Analyst"


def test_one_visitor_does_not_change_another():
    first, second = start(), start()
    first.switch_page("views/guided_demo.py")
    first.run()
    click(first, "a_go")
    n1 = first.session_state["ws_conn"].execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    n2 = second.session_state["ws_conn"].execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    assert n1 == n2 + 1
    assert first.session_state["ws_conn"] is not second.session_state["ws_conn"]


def test_approval_needs_the_supervisor_role_in_the_tracker():
    at = start()
    conn = at.session_state["ws_conn"]
    rid = conn.execute("SELECT request_id FROM requests WHERE status = 'Awaiting approval'").fetchone()[0]
    at.switch_page("views/tracker.py")
    at.run()
    at.selectbox(key="t_open").select(rid)
    at.run()
    assert not [b for b in at.button if b.key == f"t_appr_{rid}"]
    assert any("Supervisor role" in i.value for i in at.info)
    at.sidebar.radio(key="role").set_value("Supervisor")
    at.run()
    click(at, f"t_appr_{rid}")
    assert conn.execute("SELECT status FROM requests WHERE request_id = ?", (rid,)).fetchone()[0] == "Ready to bill"
