"""Version 1 figures must not change.

The expected values were produced by running the formulas in the v1.0 app.py
(tag v1.0) against the same workbook, for three filter selections.
"""
import pytest

from core import receivables as rc

V1_EXPECTED = {
    (): dict(billed=67744340.37, collected=52881140.22, outstanding=13774599.20, overdue_amt=10215934.14,
             over_90=7121080.17, over_90_n=198, avg_dpd=238.2327, cycle=28.0404, unbilled=2574504.28,
             write_offs=1088601.07, dispute_rate=0.0392, refund_recent=15.4545, refund_before=62.1481),
    ("Northern",): dict(billed=14618761.28, collected=11391574.02, outstanding=3046209.70, overdue_amt=2235214.06,
                        over_90=1673261.96, over_90_n=49, avg_dpd=250.4265, cycle=30.0237, unbilled=364370.42,
                        write_offs=180977.55, dispute_rate=0.05, refund_recent=15.375, refund_before=69.3333),
    ("Third-Party Damage Recovery", "Contractor"): dict(
        billed=6028512.10, collected=3728615.51, outstanding=1959254.58, overdue_amt=1766455.73, over_90=1516614.18,
        over_90_n=42, avg_dpd=275.5306, cycle=46.7692, unbilled=460808.57, write_offs=340642.00,
        dispute_rate=0.0888, refund_recent=20.3333, refund_before=58.1667),
}
FILTERS = {
    (): rc.Filters(),
    ("Northern",): rc.Filters(regions=["Northern"]),
    ("Third-Party Damage Recovery", "Contractor"): rc.Filters(categories=["Third-Party Damage Recovery"],
                                                              ctypes=["Contractor"]),
}


@pytest.fixture(scope="module")
def frames():
    return rc.load_data()


@pytest.mark.parametrize("key", list(V1_EXPECTED))
def test_v1_figures_unchanged(frames, key):
    m = rc.compute(frames, FILTERS[key])
    for name, expected in V1_EXPECTED[key].items():
        assert getattr(m, name) == pytest.approx(expected, abs=0.005), name


def test_headline_figures_match_the_interview_version(frames):
    m = rc.compute(frames)
    assert rc.money(m.billed) == "$67.74M"
    assert f"{m.collection_rate:.1%}" == "78.1%"
    assert rc.money(m.outstanding) == "$13.77M"
    assert rc.money(m.overdue_amt) == "$10.22M"
    assert rc.money(m.over_90) == "$7.12M"
    assert rc.money(m.by_category.loc["Third-Party Damage Recovery", "OverdueAR"]) == "$4.92M"
    assert round(m.cycle_by_cat["Third-Party Damage Recovery"]) == 47
    assert m.by_category.index[0] == "Third-Party Damage Recovery"
    assert m.top_customers.iloc[0]["CustomerName"] == "Clearwater Insurance"


def test_reporting_date_is_fixed():
    assert str(rc.AS_OF.date()) == "2026-09-30"


def test_reminder_is_a_template_draft(frames):
    m = rc.compute(frames)
    customer = m.top_customers.iloc[0]["CustomerName"]
    invoices = rc.overdue_invoices_for(m, customer)
    subject, body = rc.reminder_email(customer, invoices, second=False)
    assert f"${invoices['Balance'].sum():,.2f}" in subject
    assert all(i in body for i in invoices["InvoiceID"])


def test_filters_narrow_every_table(frames):
    f = rc.Filters(regions=["Northern"], categories=["Customer-Requested Work"], ctypes=["Individual"])
    m = rc.compute(frames, f)
    assert set(m.inv["Region"]) == {"Northern"}
    assert set(m.inv["BillingCategory"]) == {"Customer-Requested Work"}
    assert set(m.inv["CustomerType"]) == {"Individual"}
    assert set(m.pay["Region"]) <= {"Northern"} and set(m.req["Region"]) <= {"Northern"}
    assert set(m.cases["InvoiceID"]) <= set(m.inv["InvoiceID"])
    assert m.billed < rc.compute(frames).billed


def test_collections_ranking_uses_overdue_open_invoices(frames):
    m = rc.compute(frames)
    top = m.top_customers
    assert top["OverdueAR"].is_monotonic_decreasing
    first = top.iloc[0]["CustomerName"]
    own = m.inv[(m.inv["CustomerName"] == first) & m.inv["Status"].isin(rc.OPEN_STATUSES) & (m.inv["DaysPastDue"] > 0)]
    assert own["Balance"].sum() == pytest.approx(top.iloc[0]["OverdueAR"])
    assert top["OverdueAR"].sum() == pytest.approx(m.overdue_amt)
