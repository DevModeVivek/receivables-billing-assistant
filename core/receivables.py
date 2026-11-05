"""Version 1 receivables and billing figures.

Every formula here is moved unchanged from the Version 1 app. The reporting
snapshot is fixed at 30 Sep 2026 and is kept separate from the live workflow
demo. Nothing in this module uses Streamlit, so it can be tested directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "billing_sample_data.xlsx"
AS_OF = pd.Timestamp(date(2026, 9, 30))
AS_OF_LABEL = "30 Sep 2026"
OPEN_STATUSES = ["Open", "Disputed"]
AGING_ORDER = ["Current", "1-30", "31-60", "61-90", "90+"]
SLOW_CATEGORY = "Third-Party Damage Recovery"
ACTIVE_CASE_STATUSES = ["Open", "Escalated", "Payment Plan", "Dispute Under Review"]
RECENT_REFUNDS_FROM = "2026-04-01"
EARLIER_REFUNDS_BEFORE = "2025-07-01"
EARLIER_REFUNDS_LABEL = "the first half of 2025 and earlier"

# Plain-language definitions shown next to each figure
DEFINITIONS = {
    "Total billed": "Sum of all invoice amounts issued.",
    "Collection rate": "Payments received divided by total billed.",
    "Outstanding": "Unpaid balance on open and disputed invoices.",
    "Overdue": "Outstanding balance on invoices past their due date at 30 Sep 2026.",
    "Over 90 days": "Outstanding balance more than 90 days past due.",
    "Avg days to invoice": "Average days from work completed to invoice date.",
    "Unbilled backlog": "Estimated value of completed work with no invoice yet.",
    "Dispute rate": "Share of invoices with status Disputed.",
    "Written off": "Value of invoices with status Written Off.",
    "Refund turnaround": "Average days from refund request to approval.",
}


@dataclass
class Frames:
    """The Version 1 tables, after the same merges and derived columns as Version 1."""
    inv: pd.DataFrame
    pay: pd.DataFrame
    req: pd.DataFrame
    cases: pd.DataFrame
    refunds: pd.DataFrame
    customers: pd.DataFrame


def load_data(path: Path = DATA_FILE) -> Frames:
    sheets = pd.read_excel(path, sheet_name=None)
    customers_full = sheets["Customers"]
    customers = customers_full[["CustomerID", "CustomerName", "CustomerType", "Region"]]
    inv = sheets["Invoices"].merge(customers.drop(columns="Region"), on="CustomerID")
    inv["Balance"] = inv["InvoiceAmount"] - inv["AmountPaid"]
    inv["DaysPastDue"] = (AS_OF - inv["DueDate"]).dt.days
    inv["BillingCycleDays"] = (inv["InvoiceDate"] - inv["WorkCompletedDate"]).dt.days
    inv["Month"] = inv["InvoiceDate"].dt.to_period("M").dt.to_timestamp()
    inv["Quarter"] = inv["InvoiceDate"].dt.to_period("Q")
    inv["AgingBucket"] = pd.cut(inv["DaysPastDue"], [-10_000, 0, 30, 60, 90, 10_000], labels=AGING_ORDER).astype(str)
    inv.loc[~inv["Status"].isin(OPEN_STATUSES), "AgingBucket"] = None
    pay = sheets["Payments"].merge(inv[["InvoiceID", "Region", "BillingCategory", "CustomerType"]], on="InvoiceID")
    pay["Month"] = pay["PaymentDate"].dt.to_period("M").dt.to_timestamp()
    req = sheets["BillingRequests"].merge(customers[["CustomerID", "CustomerType"]], on="CustomerID")
    cases = sheets["CollectionCases"]
    refunds = sheets["Refunds"].merge(customers, on="CustomerID")
    refunds["DaysToApprove"] = (refunds["ApprovalDate"] - refunds["RequestDate"]).dt.days
    refunds["Quarter"] = refunds["RequestDate"].dt.to_period("Q")
    return Frames(inv, pay, req, cases, refunds, customers_full)


@dataclass
class Filters:
    regions: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    ctypes: List[str] = field(default_factory=list)

    def text(self) -> str:
        return ", ".join(self.regions + self.categories + self.ctypes) or "All regions and categories"


def apply_filters(df: pd.DataFrame, filters: Filters) -> pd.DataFrame:
    for column, chosen in [("Region", filters.regions), ("BillingCategory", filters.categories),
                           ("CustomerType", filters.ctypes)]:
        if chosen and column in df.columns:
            df = df[df[column].isin(chosen)]
    return df


@dataclass
class Metrics:
    """Every Version 1 figure for one filter selection."""
    filters: Filters
    inv: pd.DataFrame
    pay: pd.DataFrame
    req: pd.DataFrame
    refunds: pd.DataFrame
    cases: pd.DataFrame
    unpaid: pd.DataFrame
    overdue: pd.DataFrame
    pending: pd.DataFrame
    billed: float
    collected: float
    outstanding: float
    overdue_amt: float
    over_90: float
    over_90_n: int
    avg_dpd: float
    cycle: float
    unbilled: float
    write_offs: float
    dispute_rate: float
    refund_recent: float
    refund_before: float
    by_category: pd.DataFrame
    by_aging: pd.Series
    cycle_by_cat: pd.Series
    by_ctype: pd.Series
    by_region: pd.Series
    top_customers: pd.DataFrame

    @property
    def collection_rate(self) -> Optional[float]:
        return self.collected / self.billed if self.billed else None

    @property
    def active_cases(self) -> int:
        return int(self.cases["CaseStatus"].isin(ACTIVE_CASE_STATUSES).sum())

    @property
    def write_off_review(self) -> int:
        return int((self.cases["CaseStatus"] == "Write-Off Recommended").sum())


def compute(frames: Frames, filters: Optional[Filters] = None) -> Metrics:
    filters = filters or Filters()
    inv, pay, req, refunds = (apply_filters(d, filters) for d in
                              (frames.inv, frames.pay, frames.req, frames.refunds))
    cases = frames.cases[frames.cases["InvoiceID"].isin(inv["InvoiceID"])]
    unpaid = inv[inv["Status"].isin(OPEN_STATUSES)]
    overdue = unpaid[unpaid["DaysPastDue"] > 0]
    pending = req[req["RequestStatus"] == "Pending Invoice"]

    by_category = (overdue.groupby("BillingCategory")
                   .agg(OverdueAR=("Balance", "sum"), Invoices=("InvoiceID", "count"))
                   .sort_values("OverdueAR", ascending=False))
    top_customers = (overdue.groupby(["CustomerName", "CustomerType"])
                     .agg(OverdueAR=("Balance", "sum"), Invoices=("InvoiceID", "count"),
                          OldestDays=("DaysPastDue", "max"))
                     .sort_values("OverdueAR", ascending=False).reset_index())
    return Metrics(
        filters=filters, inv=inv, pay=pay, req=req, refunds=refunds, cases=cases,
        unpaid=unpaid, overdue=overdue, pending=pending,
        billed=float(inv["InvoiceAmount"].sum()),
        collected=float(pay["AmountPaid"].sum()),
        outstanding=float(unpaid["Balance"].sum()),
        overdue_amt=float(overdue["Balance"].sum()),
        over_90=float(unpaid.loc[unpaid["AgingBucket"] == "90+", "Balance"].sum()),
        over_90_n=int((unpaid["AgingBucket"] == "90+").sum()),
        avg_dpd=float(overdue["DaysPastDue"].mean()) if len(overdue) else 0.0,
        cycle=float(inv["BillingCycleDays"].mean()) if len(inv) else 0.0,
        unbilled=float(pending["EstimatedAmount"].sum()),
        write_offs=float(inv.loc[inv["Status"] == "Written Off", "InvoiceAmount"].sum()),
        dispute_rate=float((inv["Status"] == "Disputed").mean()) if len(inv) else 0.0,
        refund_recent=float(refunds.loc[refunds["RequestDate"] >= RECENT_REFUNDS_FROM, "DaysToApprove"].mean()),
        refund_before=float(refunds.loc[refunds["RequestDate"] < EARLIER_REFUNDS_BEFORE, "DaysToApprove"].mean()),
        by_category=by_category,
        by_aging=unpaid.groupby("AgingBucket")["Balance"].sum().reindex(AGING_ORDER).fillna(0),
        cycle_by_cat=inv.groupby("BillingCategory")["BillingCycleDays"].mean().sort_values(),
        by_ctype=overdue.groupby("CustomerType")["Balance"].sum().sort_values(ascending=False),
        by_region=overdue.groupby("Region")["Balance"].sum().sort_values(ascending=False),
        top_customers=top_customers,
    )


def money(x: float) -> str:
    if abs(x) >= 1_000_000:
        return f"${x / 1_000_000:,.2f}M"
    if abs(x) >= 1_000:
        return f"${x / 1_000:,.0f}K"
    return f"${x:,.0f}"


def quarter_labels(periods) -> List[str]:
    return [f"Q{p.quarter} {p.year}" for p in periods]


def monthly_trend(m: Metrics) -> pd.DataFrame:
    trend = pd.DataFrame({"Billed": m.inv.groupby("Month")["InvoiceAmount"].sum(),
                          "Collected": m.pay.groupby("Month")["AmountPaid"].sum()}).fillna(0)
    return trend[trend.index <= AS_OF]


def slow_category_by_quarter(m: Metrics) -> pd.DataFrame:
    inv = m.inv
    q = inv.assign(Group=inv["BillingCategory"].where(inv["BillingCategory"] == SLOW_CATEGORY, "Other categories"))
    q = q.groupby(["Quarter", "Group"])["BillingCycleDays"].mean().unstack()
    q.index = quarter_labels(q.index)
    return q


def refund_by_quarter(m: Metrics) -> pd.Series:
    r = m.refunds.groupby("Quarter")["DaysToApprove"].mean().dropna()
    r.index = quarter_labels(r.index)
    return r


def overdue_invoices_for(m: Metrics, customer: str) -> pd.DataFrame:
    return (m.overdue[m.overdue["CustomerName"] == customer]
            [["InvoiceID", "BillingCategory", "InvoiceDate", "DueDate", "Balance", "DaysPastDue", "Status"]]
            .sort_values("DaysPastDue", ascending=False))


def reminder_email(customer: str, invoices: pd.DataFrame, second: bool) -> Tuple[str, str]:
    """A payment reminder written from a fixed template. It is a draft; nothing is sent."""
    total = float(invoices["Balance"].sum())
    lines = "\n".join(
        f"- Invoice {r.InvoiceID} ({r.BillingCategory}), due {r.DueDate:%d %b %Y}: ${r.Balance:,.2f}"
        for r in invoices.itertuples())
    if second:
        subject = f"Second reminder: overdue balance of ${total:,.2f}"
        ask = ("Our records show this balance is still unpaid after our earlier reminder. "
               "Please arrange payment within 10 business days, or contact us if you have a question about the charges.")
    else:
        subject = f"Payment reminder: overdue balance of ${total:,.2f}"
        ask = ("If you have already paid, thank you, and please disregard this note. "
               "If you have a question about any of these charges, reply to this email and we will help.")
    body = (f"Dear {customer},\n\nOur records show the following invoices are past due:\n\n{lines}\n\n"
            f"Total overdue: ${total:,.2f}\n\n{ask}\n\nThank you,\nBilling Operations")
    return subject, body


def summary_lines(m: Metrics) -> Dict[str, List[str]]:
    """The labelled facts the assistant is given, one per line (as in Version 1)."""
    metrics = {
        "Total billed": f"${m.billed:,.0f}", "Collected": f"${m.collected:,.0f}",
        "Collection rate": f"{m.collection_rate:.1%}" if m.billed else "-",
        "Outstanding": f"${m.outstanding:,.0f}", "Overdue": f"${m.overdue_amt:,.0f}",
        "Over 90 days past due": f"${m.over_90:,.0f}",
        "Average days past due (overdue invoices)": f"{m.avg_dpd:.0f}",
        "Average days to invoice": f"{m.cycle:.1f}", "Unbilled backlog": f"${m.unbilled:,.0f}",
        "Written off": f"${m.write_offs:,.0f}", "Dispute rate": f"{m.dispute_rate:.1%}",
        "Refund turnaround, requests since 1 Apr 2026 (days)":
            f"{m.refund_recent:.0f}" if pd.notna(m.refund_recent) else "-",
        "Active collection cases": f"{m.active_cases}",
    }
    return {
        "Headline figures": [f"{k}: {v}" for k, v in metrics.items()],
        "Overdue balance by billing category": [
            f"{cat}: ${row.OverdueAR:,.0f} across {row.Invoices} invoices" for cat, row in m.by_category.iterrows()],
        "Outstanding balance by age (days past due)": [f"{b}: ${v:,.0f}" for b, v in m.by_aging.items()],
        "Average days to invoice by category": [f"{cat}: {v:.1f} days" for cat, v in m.cycle_by_cat.items()],
        "Overdue balance by customer type": [f"{t}: ${v:,.0f}" for t, v in m.by_ctype.items()],
        "Overdue balance by region": [f"{r}: ${v:,.0f}" for r, v in m.by_region.items()],
        "Top 10 overdue customers, largest first": [
            f"{row.CustomerName} (customer type: {row.CustomerType}): ${row.OverdueAR:,.0f} overdue across "
            f"{row.Invoices} invoices, oldest invoice {row.OldestDays} days past due"
            for row in m.top_customers.head(10).itertuples()],
    }
