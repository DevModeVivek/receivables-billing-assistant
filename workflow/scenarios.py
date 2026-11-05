"""The three guided demo scenarios.

A. A complete request goes straight to Ready to bill.
B. A request with missing information is held, a follow-up is drafted, the
   visitor adds the missing details, the checks run again and a supervisor
   (simulated role) approves it because it is over the limit.
C. Ready requests go to billing in one batch. The billing system's sample
   confirmation has one amount keyed with two digits swapped. Reconciliation
   catches it, so that request is not marked billed until a corrected invoice
   that matches is recorded.

Every step goes through the same intake, checks, tracker and reconciliation as
the rest of the app. Nothing here is a mock-up.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from workflow import extract, sample_data, store

A_ACCOUNT, A_CUSTOMER = "C0011", "Redrock Paving"
B_ACCOUNT, B_CUSTOMER = "C0012", "Pinecrest Paving"
B_AMOUNT = 58_240.50
B_CLAIM = "CLM-20931"


def fresh_work_order(conn) -> str:
    """A work order number not used by any request yet, so a scenario can be run again."""
    return f"WO-{max(_used_numbers(conn) + [418_000]) + 11:06d}"


def _used_numbers(conn) -> List[int]:
    out = []
    for (wo,) in conn.execute("SELECT work_order FROM requests"):
        m = re.fullmatch(r"WO-?(\d{6})", str(wo or ""))
        if m:
            out.append(int(m.group(1)))
    return out


def email_a(conn, today: date) -> str:
    done = today - timedelta(days=4)
    return f"""From: Grace Liu <grace.liu@example.com>
Subject: Billing request - meter base repair

Submitting team: Field Operations
Customer account number: {A_ACCOUNT}
Customer name: {A_CUSTOMER}
Billing category: Miscellaneous
Work order number: {fresh_work_order(conn)}
Work completed date: {done.isoformat()}
Description of work: Meter base repair after contractor damage
Cost centre: 4320
Labour cost: 1,240.00
Materials cost: 385.50
Equipment cost: 210.00
Total amount to bill: 1,835.50"""


def email_b(conn, today: date) -> str:
    """A damage recovery request over the approval limit, missing the claim number and documents."""
    done = today - timedelta(days=6)
    return f"""From: Priya Nair <priya.nair@example.com>
Subject: Damage recovery - {B_CUSTOMER}

Submitting team: Claims
Customer account number: {B_ACCOUNT}
Customer name: {B_CUSTOMER}
Billing category: Third-Party Damage Recovery
Work order number: {fresh_work_order(conn)}
Work completed date: {done.isoformat()}
Incident date: {(done - timedelta(days=3)).isoformat()}
Description of work: Underground cable damaged during excavation
Cost centre: 4210
Labour cost: 38,420.00
Materials cost: 14,915.75
Equipment cost: 4,904.75
Total amount to bill: {B_AMOUNT:,.2f}

Photos to follow."""


def reply_b(request_id: str) -> str:
    return f"""From: Priya Nair <priya.nair@example.com>
Subject: RE: Information needed: billing request {request_id}

Hi,

The claim number is {B_CLAIM}. I have attached the damage report and the photos.

Thanks,
Priya"""


def log_email(conn, text: str, user: str, now: datetime, customers: dict) -> Dict:
    fields, _ = extract.read_email(text)
    rid, findings = store.add_request(conn, fields, "Email", user, now, customers)
    req = store.get_request(conn, rid)
    return {"request_id": rid, "status": req["status"], "findings": findings, "email": text, "request": req}


def correct_b(conn, request_id: str, claim: str, docs: bool, user: str, now: datetime, customers: dict):
    """What the analyst does with the reply: add the missing details. The checks run again."""
    return store.update_request(conn, request_id, {"claim_reference": claim, "supporting_docs": "Yes" if docs else "No"},
                                user, now, customers, note="Requester replied")


def sample_confirmation(upload: pd.DataFrame, wrong_reference: Optional[str]) -> pd.DataFrame:
    """A sample billing system confirmation. One amount has two digits swapped, the most common keying error."""
    conf = pd.DataFrame({"Reference": upload["Reference"],
                         "Invoice Number": [f"9{4100000 + i * 137:07d}" for i in range(len(upload))],
                         "Invoice Amount": upload["Amount"].astype(float)})
    idx = conf.index[conf["Reference"] == wrong_reference]
    i = int(idx[0]) if len(idx) else len(conf) - 1
    conf.loc[i, "Invoice Amount"] = sample_data._keying_error(float(conf.loc[i, "Invoice Amount"]))
    return conf


def send_batch(conn, user: str, now: datetime) -> Dict:
    batch_id, upload = store.create_batch(conn, user, now)
    if batch_id is None:
        return {}
    return {"batch_id": batch_id, "upload": upload, "count": len(upload),
            "control_total": round(float(upload["Amount"].sum()), 2)}


def reconcile(conn, batch_id: str, confirmation: pd.DataFrame, user: str, now: datetime) -> Dict:
    recon = store.reconcile(conn, batch_id, confirmation)
    counts = store.confirm_batch(conn, batch_id, recon, user, now)
    held = recon[recon["result"] != "Matched"]
    out = {"recon": recon, "counts": counts, "held": held}
    if len(held):
        t = held.iloc[0]
        out.update(target=t.request_id, requested=float(t.total_amount), invoiced=float(t.invoice_amount),
                   invoice_number=str(t.invoice_number))
    return out


def record_corrected_invoice(conn, result: Dict, user: str, now: datetime) -> str:
    """The billing system reissues the invoice for the right amount; it is recorded only if it matches."""
    corrected = f"{result['invoice_number'][:-1]}{(int(result['invoice_number'][-1]) + 1) % 10}"
    store.resolve_exception(conn, result["target"], corrected, result["requested"], user, now,
                            "Invoice reissued in billing system")
    return corrected


def billed_count(conn, batch_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM requests WHERE batch_id = ? AND status = 'Billed'",
                        (batch_id,)).fetchone()[0]
