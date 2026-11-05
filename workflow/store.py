"""The request tracker: requests, checks, approvals, batches and history.

Each visitor gets their own in-memory SQLite database, so nothing is kept
between visits and one visitor never sees another's changes.

Every change goes through these functions, so each one is checked against the
allowed status moves and written to the history.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pandas as pd

from workflow import rules

SUPERVISOR = "Supervisor"
ANALYST = "Analyst"
REMINDER_AFTER_DAYS = 3

# The only status moves allowed. Anything else is refused.
_CHECKED = {"Needs information", "Awaiting approval", "Ready to bill", "Cancelled"}
TRANSITIONS = {
    "Received": _CHECKED,
    "Needs information": _CHECKED,
    "Awaiting approval": _CHECKED,
    "Ready to bill": _CHECKED | {"In billing batch"},
    "In billing batch": {"Billed"},
    "Billed": set(),
    "Cancelled": set(),
}
EDITABLE = {"Received", "Needs information", "Awaiting approval", "Ready to bill"}


class TransitionError(ValueError):
    """A status move that the process does not allow."""


def check_move(current: str, new: str, request_id: str = "") -> None:
    if new == current and new in EDITABLE:
        return
    if new not in TRANSITIONS.get(current, set()):
        raise TransitionError(f"{request_id or 'Request'} cannot move from {current} to {new}.")

_FIELD_COLS = ", ".join(f"{f} {'REAL' if f in rules.NUMBER_FIELDS else 'TEXT'}" for f in rules.REQUEST_FIELDS)
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY,
    received_at TEXT, source TEXT, received_by TEXT, status TEXT,
    {_FIELD_COLS},
    first_pass_clean INTEGER, check_runs INTEGER DEFAULT 0, followups_sent INTEGER DEFAULT 0,
    last_followup_at TEXT, approved_by TEXT, approved_at TEXT, ready_at TEXT,
    batch_id TEXT, invoice_number TEXT, billed_at TEXT, exception TEXT, cancelled_reason TEXT
);
CREATE TABLE IF NOT EXISTS checks_log (
    request_id TEXT, run_at TEXT, run_no INTEGER, rule_id TEXT, severity TEXT, field TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY, created_at TEXT, created_by TEXT, request_count INTEGER,
    control_total REAL, status TEXT, confirmed_at TEXT, confirmed_by TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user TEXT, request_id TEXT, action TEXT, detail TEXT
);
"""


def ts(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def is_empty(conn) -> bool:
    return conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0


def log(conn, now, user, request_id, action, detail=""):
    conn.execute("INSERT INTO events (ts, user, request_id, action, detail) VALUES (?, ?, ?, ?, ?)",
                 (ts(now), user, request_id, action, detail))


def all_requests(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM requests ORDER BY request_id")]


def get_request(conn, request_id) -> dict:
    row = conn.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,)).fetchone()
    return dict(row) if row else {}


def table(conn, sql, params=()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)


def clean_fields(fields: dict) -> dict:
    out = {}
    for f in rules.REQUEST_FIELDS:
        v = fields.get(f)
        if f in rules.NUMBER_FIELDS:
            out[f] = rules.to_number(v)
        else:
            out[f] = None if rules.blank(v) else str(v).strip()
    for f in ("customer_account", "work_order"):
        if out[f]:
            out[f] = out[f].upper()
    for f in ("work_completed_date", "incident_date"):
        d = rules.to_date(out[f])
        if d:
            out[f] = d.isoformat()
    return out


def findings_for(conn, req: dict, customers: dict, today) -> list:
    others = [r for r in all_requests(conn) if r["request_id"] != req["request_id"]]
    return rules.run_checks(req, customers, others, today)


def _apply_checks(conn, request_id, customers, now, user) -> list:
    req = get_request(conn, request_id)
    findings = findings_for(conn, req, customers, now.date())
    run_no = (req.get("check_runs") or 0) + 1
    conn.executemany(
        "INSERT INTO checks_log VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(request_id, ts(now), run_no, f.rule_id, f.severity, f.field, f.message) for f in findings],
    )
    status = rules.decide_status(findings, approved=bool(req.get("approved_by")))
    check_move(req.get("status"), status, request_id)
    updates = {"check_runs": run_no, "status": status}
    if run_no == 1:
        updates["first_pass_clean"] = int(not any(f.severity == "Blocker" for f in findings))
    if status == "Ready to bill" and req.get("status") != "Ready to bill":
        updates["ready_at"] = ts(now)
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE requests SET {sets} WHERE request_id = ?", (*updates.values(), request_id))
    blockers = sum(f.severity == "Blocker" for f in findings)
    warnings = sum(f.severity == "Warning" for f in findings)
    log(conn, now, "System", request_id, "Checks run",
        f"Must fix: {blockers}, to check: {warnings}. Status: {status}")
    return findings


def next_request_id(conn, now) -> str:
    prefix = f"BR-{now:%y}-"
    row = conn.execute("SELECT MAX(request_id) FROM requests WHERE request_id LIKE ?", (prefix + "%",)).fetchone()
    n = int(row[0].split("-")[-1]) + 1 if row[0] else 1
    return f"{prefix}{n:04d}"


def add_request(conn, fields: dict, source: str, user: str, now: datetime, customers: dict):
    rid = next_request_id(conn, now)
    data = clean_fields(fields)
    cols = ["request_id", "received_at", "source", "received_by", "status"] + rules.REQUEST_FIELDS
    vals = [rid, ts(now), source, user, "Received"] + [data[f] for f in rules.REQUEST_FIELDS]
    conn.execute(f"INSERT INTO requests ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
    log(conn, now, user, rid, "Request logged", f"Source: {source}")
    findings = _apply_checks(conn, rid, customers, now, user)
    conn.commit()
    return rid, findings


def update_request(conn, request_id, changes: dict, user, now, customers, note="Corrected"):
    req = get_request(conn, request_id)
    if req.get("status") not in EDITABLE:
        raise TransitionError(f"{request_id} can no longer be edited (status: {req.get('status')}).")
    new = clean_fields({**req, **changes})
    diffs = [f for f in rules.REQUEST_FIELDS if new[f] != req.get(f)]
    if not diffs:
        return findings_for(conn, req, customers, now.date())
    sets = ", ".join(f"{f} = ?" for f in diffs)
    # A material change (amount, customer or category) needs a fresh approval
    reset_approval = bool(set(diffs) & set(rules.MATERIAL_FIELDS)) and bool(req.get("approved_by"))
    if reset_approval:
        sets += ", approved_by = NULL, approved_at = NULL"
    conn.execute(f"UPDATE requests SET {sets} WHERE request_id = ?", (*[new[f] for f in diffs], request_id))
    detail = "; ".join(f"{rules.FIELD_LABELS[f]}: '{req.get(f) or ''}' -> '{new[f] or ''}'" for f in diffs)
    log(conn, now, user, request_id, note, detail + (" (approval reset)" if reset_approval else ""))
    findings = _apply_checks(conn, request_id, customers, now, user)
    conn.commit()
    return findings


def record_follow_up(conn, request_id, user, now):
    req = get_request(conn, request_id)
    n = (req.get("followups_sent") or 0) + 1
    conn.execute("UPDATE requests SET followups_sent = ?, last_followup_at = ? WHERE request_id = ?",
                 (n, ts(now), request_id))
    log(conn, now, user, request_id, "Follow-up sent" if n == 1 else "Reminder sent",
        f"To {req.get('requester_email') or 'requester'}")
    conn.commit()


def approve(conn, request_id, user, now, customers):
    """Approve a request over the limit. `user` is the simulated role chosen in the app."""
    req = get_request(conn, request_id)
    if user != SUPERVISOR:
        raise PermissionError("Only a supervisor can approve requests over the limit.")
    if req.get("received_by") == user:
        raise PermissionError("The person who logged a request cannot approve it.")
    if req.get("status") != "Awaiting approval":
        raise ValueError(f"{request_id} is not awaiting approval.")
    conn.execute("UPDATE requests SET approved_by = ?, approved_at = ? WHERE request_id = ?", (user, ts(now), request_id))
    log(conn, now, user, request_id, "Approved", f"Amount ${req['total_amount']:,.2f}")
    _apply_checks(conn, request_id, customers, now, user)
    conn.commit()


def cancel(conn, request_id, user, now, reason):
    check_move(get_request(conn, request_id).get("status"), "Cancelled", request_id)
    conn.execute("UPDATE requests SET status = 'Cancelled', cancelled_reason = ? WHERE request_id = ?", (reason, request_id))
    log(conn, now, user, request_id, "Cancelled", reason)
    conn.commit()


BATCH_COLUMNS = {
    "request_id": "Reference", "customer_account": "Customer Account", "customer_name": "Customer Name",
    "billing_category": "Billing Category", "work_order": "Work Order", "work_completed_date": "Service Date",
    "cost_centre": "Cost Centre", "description": "Line Description", "total_amount": "Amount",
}


def create_batch(conn, user, now):
    ready = table(conn, "SELECT * FROM requests WHERE status = 'Ready to bill' ORDER BY request_id")
    if ready.empty:
        return None, None
    batch_id = f"BB-{now:%y%m%d-%H%M}"
    total = round(float(ready["total_amount"].sum()), 2)
    conn.execute("INSERT INTO batches VALUES (?, ?, ?, ?, ?, 'Sent to billing', NULL, NULL)",
                 (batch_id, ts(now), user, len(ready), total))
    conn.executemany("UPDATE requests SET status = 'In billing batch', batch_id = ? WHERE request_id = ?",
                     [(batch_id, r) for r in ready["request_id"]])
    for r in ready["request_id"]:
        log(conn, now, user, r, "Added to billing batch", batch_id)
    log(conn, now, user, None, "Batch created", f"{batch_id}: {len(ready)} requests, control total ${total:,.2f}")
    conn.commit()
    return batch_id, batch_file(conn, batch_id)


def batch_file(conn, batch_id) -> pd.DataFrame:
    df = table(conn, f"SELECT {', '.join(BATCH_COLUMNS)} FROM requests WHERE batch_id = ? ORDER BY request_id", (batch_id,))
    return df.rename(columns=BATCH_COLUMNS)


def reconcile(conn, batch_id, confirmation: pd.DataFrame) -> pd.DataFrame:
    """Compare what the billing system created with what was sent. Nothing is changed here."""
    sent = table(conn, "SELECT request_id, customer_account, total_amount, status FROM requests WHERE batch_id = ?",
                 (batch_id,))
    conf = confirmation.rename(columns=lambda c: str(c).strip().lower().replace(" ", "_"))
    conf = conf.rename(columns={"reference": "request_id", "amount": "invoice_amount"})
    need = {"request_id", "invoice_number", "invoice_amount"}
    if not need.issubset(conf.columns):
        raise ValueError("The confirmation file needs the columns Reference, Invoice Number and Invoice Amount.")
    conf["invoice_amount"] = conf["invoice_amount"].map(rules.to_number)
    merged = sent.merge(conf[["request_id", "invoice_number", "invoice_amount"]], on="request_id", how="outer")
    def result(r):
        if pd.isna(r["total_amount"]):
            return "Not in this batch"
        if pd.isna(r["invoice_number"]):
            return "No invoice found"
        if abs(r["invoice_amount"] - r["total_amount"]) > 0.01:
            return "Amount differs"
        return "Matched"
    merged["result"] = merged.apply(result, axis=1)
    merged["difference"] = (merged["invoice_amount"] - merged["total_amount"]).round(2)
    return merged


def confirm_batch(conn, batch_id, recon: pd.DataFrame, user, now) -> dict:
    counts = recon["result"].value_counts().to_dict()
    for r in recon.itertuples():
        if r.result == "Matched" and r.status == "In billing batch":
            conn.execute("UPDATE requests SET status = 'Billed', invoice_number = ?, billed_at = ?, exception = NULL "
                         "WHERE request_id = ?", (str(r.invoice_number), ts(now), r.request_id))
            log(conn, now, user, r.request_id, "Billed", f"Invoice {r.invoice_number}")
        elif r.result in ("Amount differs", "No invoice found") and r.status == "In billing batch":
            diff = r.invoice_amount - r.total_amount
            note = (f"Invoice {r.invoice_number} is ${r.invoice_amount:,.2f}, request is ${r.total_amount:,.2f} "
                    f"(difference {'-' if diff < 0 else '+'}${abs(diff):,.2f})"
                    if r.result == "Amount differs" else "No invoice in the billing system confirmation")
            conn.execute("UPDATE requests SET exception = ? WHERE request_id = ?", (note, r.request_id))
            log(conn, now, user, r.request_id, "Reconciliation exception", note)
    open_left = conn.execute("SELECT COUNT(*) FROM requests WHERE batch_id = ? AND status = 'In billing batch'",
                             (batch_id,)).fetchone()[0]
    if open_left == 0:
        conn.execute("UPDATE batches SET status = 'Confirmed', confirmed_at = ?, confirmed_by = ? WHERE batch_id = ?",
                     (ts(now), user, batch_id))
    log(conn, now, user, None, "Batch reconciled", f"{batch_id}: " + json.dumps(counts))
    conn.commit()
    return counts


def resolve_exception(conn, request_id, invoice_number, invoice_amount, user, now, note):
    """Close a reconciliation exception once the billing system shows a corrected invoice.

    The corrected invoice must match the request amount; otherwise nothing changes.
    """
    req = get_request(conn, request_id)
    check_move(req.get("status"), "Billed", request_id)
    if not req.get("exception"):
        raise TransitionError(f"{request_id} has no reconciliation exception to resolve.")
    amount = rules.to_number(invoice_amount)
    if amount is None or abs(amount - req["total_amount"]) > 0.01:
        raise ValueError(f"The corrected invoice must be ${req['total_amount']:,.2f} to match the request.")
    conn.execute("UPDATE requests SET status = 'Billed', invoice_number = ?, billed_at = ?, exception = NULL "
                 "WHERE request_id = ?", (invoice_number, ts(now), request_id))
    log(conn, now, user, request_id, "Exception resolved", f"{note} (invoice {invoice_number}, ${amount:,.2f})")
    batch_id = get_request(conn, request_id)["batch_id"]
    left = conn.execute("SELECT COUNT(*) FROM requests WHERE batch_id = ? AND status = 'In billing batch'",
                        (batch_id,)).fetchone()[0]
    if left == 0:
        conn.execute("UPDATE batches SET status = 'Confirmed', confirmed_at = ?, confirmed_by = ? WHERE batch_id = ?",
                     (ts(now), user, batch_id))
    conn.commit()


def next_action(req: dict, now: datetime) -> str:
    s = req["status"]
    if s == "Needs information":
        if not req.get("followups_sent"):
            return "Send follow-up"
        sent = datetime.strptime(req["last_followup_at"], "%Y-%m-%d %H:%M")
        days = (now.date() - sent.date()).days
        if days >= REMINDER_AFTER_DAYS:
            return "Reminder due"
        return "Awaiting reply (asked today)" if days == 0 else f"Awaiting reply ({days} day{'s' if days > 1 else ''})"
    if s == "Awaiting approval":
        return "Supervisor approval"
    if s == "Ready to bill":
        return "Add to billing batch"
    if s == "In billing batch":
        return "Check exception" if req.get("exception") else "Confirm with billing system"
    return "None"
