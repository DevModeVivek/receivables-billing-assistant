"""Checks run on every billing request before it can be billed.

These are plain rules, not AI, so they give the same answer every time.
Each check returns plain-language results:
- "Must fix" (internally "Blocker") stops the request until it is corrected,
- "Warning" asks the analyst to take a look,
- "Needs approval" (internally "Approval") sends the request to a supervisor.
A request with none of these, or only warnings, is "Ready".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher

# Illustrative settings for the demo. A real team would use its own policy and rate card.
APPROVAL_LIMIT = 50_000.00
POLE_ATTACHMENT_RATE = 36.50  # sample rate card, per attachment
LATE_BILLING_DAYS = 180
DUPLICATE_WINDOW_DAYS = 30
COST_CENTRES = ["4110", "4120", "4210", "4310", "4320", "4410", "4510"]
TEAMS = ["Lines", "Claims", "Forestry", "Field Operations", "Joint Use", "Customer Connections"]
CATEGORIES = [
    "Third-Party Damage Recovery",
    "Joint-Use Pole Attachments",
    "Customer-Requested Work",
    "Connection & Capital Contributions",
    "Miscellaneous",
]

FIELD_LABELS = {
    "submitted_by_team": "Submitting team",
    "requester_name": "Requester name",
    "requester_email": "Requester email",
    "customer_account": "Customer account number",
    "customer_name": "Customer name",
    "billing_category": "Billing category",
    "work_order": "Work order number",
    "work_completed_date": "Work completed date",
    "description": "Description of work",
    "cost_centre": "Cost centre",
    "labour": "Labour cost",
    "materials": "Materials cost",
    "equipment": "Equipment cost",
    "total_amount": "Total amount to bill",
    "incident_date": "Incident date",
    "claim_reference": "Claim or police report number",
    "attachment_count": "Number of pole attachments",
    "contract_number": "Contract or agreement number",
    "quote_reference": "Quote reference",
    "supporting_docs": "Supporting documents attached",
}
REQUEST_FIELDS = list(FIELD_LABELS)
# How a missing field is asked for in a follow-up email, where the label alone reads badly
FIELD_ASK = {
    "supporting_docs": "Please attach the supporting documents (damage report, photos and any third-party invoices).",
    "attachment_count": "Please provide the number of pole attachments being billed.",
    "total_amount": "Please provide the total amount to bill.",
}
TEXT_FIELDS = ["submitted_by_team", "requester_name", "requester_email", "customer_account", "customer_name",
               "billing_category", "work_order", "work_completed_date", "description", "cost_centre",
               "incident_date", "claim_reference", "contract_number", "quote_reference", "supporting_docs"]
NUMBER_FIELDS = ["labour", "materials", "equipment", "total_amount", "attachment_count"]

ALWAYS_REQUIRED = ["submitted_by_team", "requester_name", "requester_email", "customer_account", "customer_name",
                   "billing_category", "work_order", "work_completed_date", "description", "cost_centre",
                   "total_amount"]
CATEGORY_REQUIRED = {
    "Third-Party Damage Recovery": ["incident_date", "claim_reference", "supporting_docs"],
    "Joint-Use Pole Attachments": ["attachment_count"],
    "Customer-Requested Work": ["quote_reference"],
    "Connection & Capital Contributions": ["contract_number"],
    "Miscellaneous": [],
}

# The catalogue shown on the Controls page. One line per check.
RULES = [
    ("REQ", "Blocker", "All required information is provided, including what the billing category needs"),
    ("CUS-1", "Blocker", "Customer account exists in the customer master"),
    ("CUS-2", "Warning", "Customer name matches the name on the account"),
    ("WO-1", "Blocker", "Work order number is in the format WO-123456"),
    ("WO-2", "Blocker", "Work order is not already on another open or billed request"),
    ("DT-1", "Blocker", "Dates are real dates and not in the future"),
    ("DT-2", "Warning", f"Work was completed within the last {LATE_BILLING_DAYS} days"),
    ("DT-3", "Warning", "Incident date is on or before the work completed date"),
    ("AMT-1", "Blocker", "Total equals labour plus materials plus equipment"),
    ("AMT-2", "Blocker", f"Pole attachment total equals attachments x ${POLE_ATTACHMENT_RATE:.2f} rate"),
    ("AMT-3", "Blocker", "Total amount is greater than zero"),
    ("APR", "Approval", f"Requests over ${APPROVAL_LIMIT:,.0f} need supervisor approval by someone other than the preparer"),
    ("DUP", "Warning", f"No request for the same customer and amount in the last {DUPLICATE_WINDOW_DAYS} days"),
    ("EML", "Warning", "Requester email address looks valid"),
    ("CC", "Blocker", "Cost centre is on the approved list"),
    ("DOC", "Blocker", "Damage recovery requests include supporting documents"),
]
RULE_TEXT = {rid: text for rid, _, text in RULES}
# How each failed check is named in reports
PROBLEM_LABEL = {
    "CUS-1": "Account not in customer master", "CUS-2": "Customer name does not match account",
    "WO-1": "Work order in the wrong format", "WO-2": "Work order already on another request",
    "DT-1": "Invalid or future date", "DT-2": "Work completed long ago", "DT-3": "Incident after work completed",
    "AMT-1": "Total does not match cost lines", "AMT-2": "Total does not match rate card",
    "AMT-3": "Amount missing or zero", "APR": "Over approval limit", "DUP": "Possible duplicate",
    "EML": "Email address not valid", "CC": "Cost centre not on approved list", "DOC": "No supporting documents",
}

OPEN_STATUSES = ["Received", "Needs information", "Awaiting approval", "Ready to bill", "In billing batch"]
ALL_STATUSES = OPEN_STATUSES + ["Billed", "Cancelled"]

# How each severity is shown on screen
SEVERITY_LABEL = {"Blocker": "Must fix", "Warning": "Warning", "Approval": "Needs approval"}
SEVERITY_ORDER = {"Blocker": 0, "Approval": 1, "Warning": 2}
# Fields whose change makes an earlier approval no longer valid
MATERIAL_FIELDS = ["total_amount", "labour", "materials", "equipment", "attachment_count", "customer_account",
                   "billing_category"]


@dataclass
class Finding:
    rule_id: str
    severity: str
    field: str
    message: str
    fix: str  # what to ask the sender for, used in follow-up emails


def blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    return str(value).strip() == ""


def to_number(value):
    if blank(value):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def to_date(value):
    if blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def required_fields(category) -> list[str]:
    return ALWAYS_REQUIRED + CATEGORY_REQUIRED.get(category, [])


def run_checks(req: dict, customers: dict, others: list[dict], today: date) -> list[Finding]:
    """Check one request.

    customers: {account number: customer name} from the customer master.
    others: every other request in the tracker (for duplicate checks).
    """
    out: list[Finding] = []
    cat = req.get("billing_category")

    def add(rule, field, message, fix):
        sev = next(s for r, s, _ in RULES if r == rule)
        out.append(Finding(rule, sev, field, message, fix))

    # REQ: required information
    for f in required_fields(cat):
        if blank(req.get(f)):
            label = "Supporting documents" if f == "supporting_docs" else FIELD_LABELS[f]
            add("REQ", f, f"{label} {'are' if f == 'supporting_docs' else 'is'} missing",
                FIELD_ASK.get(f, f"Please provide the {FIELD_LABELS[f].lower()}."))
    if not blank(cat) and cat not in CATEGORIES:
        add("REQ", "billing_category", f"Billing category '{cat}' is not a recognised category",
            "Please confirm the billing category (" + ", ".join(CATEGORIES) + ").")

    # CUS: customer master
    acct = str(req.get("customer_account") or "").strip().upper()
    if acct:
        if acct not in customers:
            add("CUS-1", "customer_account", f"Account {acct} is not in the customer master",
                f"Account {acct} could not be found. Please confirm the customer account number.")
        elif not blank(req.get("customer_name")):
            on_file = customers[acct]
            given = str(req["customer_name"]).strip()
            if SequenceMatcher(None, given.lower(), on_file.lower()).ratio() < 0.85:
                add("CUS-2", "customer_name", f"Name '{given}' does not match the account name '{on_file}'",
                    f"The account {acct} is registered to {on_file}, not {given}. Please confirm which customer to bill.")

    # WO: work order
    wo = str(req.get("work_order") or "").strip().upper()
    if wo:
        if not re.fullmatch(r"WO-\d{6}", wo):
            add("WO-1", "work_order", f"Work order '{wo}' is not in the format WO-123456",
                "Please confirm the work order number (format WO-123456).")
        else:
            clash = [o for o in others if str(o.get("work_order") or "").strip().upper() == wo
                     and o.get("status") != "Cancelled" and o.get("request_id") != req.get("request_id")]
            if clash:
                c = clash[0]
                add("WO-2", "work_order", f"Work order {wo} is already on request {c['request_id']} ({c['status']})",
                    f"Work order {wo} is already on billing request {c['request_id']}. "
                    "Please confirm whether this is a new charge or a duplicate.")

    # DT: dates
    done = to_date(req.get("work_completed_date"))
    if not blank(req.get("work_completed_date")):
        if done is None:
            add("DT-1", "work_completed_date", "Work completed date is not a valid date",
                "Please confirm the date the work was completed.")
        elif done > today:
            add("DT-1", "work_completed_date", f"Work completed date {done:%d %b %Y} is in the future",
                "The work completed date is in the future. Please confirm the correct date.")
        elif (today - done).days > LATE_BILLING_DAYS:
            add("DT-2", "work_completed_date", f"Work was completed {(today - done).days} days ago",
                "")
    incident = to_date(req.get("incident_date"))
    if not blank(req.get("incident_date")) and incident is None:
        add("DT-1", "incident_date", "Incident date is not a valid date", "Please confirm the incident date.")
    elif incident and incident > today:
        add("DT-1", "incident_date", "Incident date is in the future", "Please confirm the incident date.")
    elif incident and done and incident > done:
        add("DT-3", "incident_date", "Incident date is after the work completed date", "")

    # AMT: amounts
    total = to_number(req.get("total_amount"))
    if not blank(req.get("total_amount")) and total is None:
        add("AMT-3", "total_amount", "Total amount is not a number", "Please confirm the total amount to bill.")
    elif total is not None and total <= 0:
        add("AMT-3", "total_amount", "Total amount must be greater than zero", "Please confirm the total amount to bill.")
    if total is not None and total > 0:
        if cat == "Joint-Use Pole Attachments":
            count = to_number(req.get("attachment_count"))
            if count is not None:
                expected = round(count * POLE_ATTACHMENT_RATE, 2)
                if abs(expected - total) > 0.01:
                    add("AMT-2", "total_amount",
                        f"Total ${total:,.2f} does not equal {count:,.0f} attachments x ${POLE_ATTACHMENT_RATE:.2f} = ${expected:,.2f}",
                        f"The total does not match the rate card ({count:,.0f} attachments x ${POLE_ATTACHMENT_RATE:.2f} = "
                        f"${expected:,.2f}). Please confirm the attachment count or the amount.")
        else:
            parts = [to_number(req.get(f)) for f in ("labour", "materials", "equipment")]
            if any(p is not None for p in parts):
                lines = round(sum(p or 0 for p in parts), 2)
                if abs(lines - total) > 0.01:
                    add("AMT-1", "total_amount",
                        f"Total ${total:,.2f} does not equal the cost lines (${lines:,.2f})",
                        f"The total (${total:,.2f}) does not equal labour + materials + equipment (${lines:,.2f}). "
                        "Please confirm the correct amounts.")
        if total > APPROVAL_LIMIT:
            add("APR", "total_amount", f"${total:,.2f} is over the ${APPROVAL_LIMIT:,.0f} approval limit", "")

        # DUP: same customer and amount recently
        received = to_date(req.get("received_at")) or today
        for o in others:
            if o.get("request_id") == req.get("request_id") or o.get("status") == "Cancelled":
                continue
            o_total = to_number(o.get("total_amount"))
            o_date = to_date(o.get("received_at"))
            if (str(o.get("customer_account") or "").strip().upper() == acct and acct and o_total is not None
                    and abs(o_total - total) < 0.01 and o_date and abs((received - o_date).days) <= DUPLICATE_WINDOW_DAYS):
                add("DUP", "total_amount", f"Same customer and amount as request {o['request_id']}", "")
                break

    # EML, CC, DOC
    email = str(req.get("requester_email") or "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", email):
        add("EML", "requester_email", f"Email '{email}' does not look valid", "")
    cc = str(req.get("cost_centre") or "").strip()
    if cc and cc not in COST_CENTRES:
        add("CC", "cost_centre", f"Cost centre {cc} is not on the approved list",
            f"Cost centre {cc} is not on the approved list. Please confirm the cost centre.")
    if cat == "Third-Party Damage Recovery" and not blank(req.get("supporting_docs")) \
            and str(req.get("supporting_docs")).strip().lower() not in ("yes", "y", "true"):
        add("DOC", "supporting_docs", "No supporting documents (damage report, photos, invoices)",
            "Please attach the damage report, photos and any third-party invoices.")
    return out


def readiness(findings: list[Finding], approved: bool) -> str:
    """One overall result for the analyst: Must fix, Needs approval, Warning or Ready."""
    if any(f.severity == "Blocker" for f in findings):
        return "Must fix"
    if any(f.severity == "Approval" for f in findings) and not approved:
        return "Needs approval"
    if any(f.severity == "Warning" for f in findings):
        return "Warning"
    return "Ready"


def decide_status(findings: list[Finding], approved: bool) -> str:
    if any(f.severity == "Blocker" for f in findings):
        return "Needs information"
    if any(f.severity == "Approval" for f in findings) and not approved:
        return "Awaiting approval"
    return "Ready to bill"


def follow_up_email(req: dict, findings: list[Finding], sender: str) -> tuple[str, str]:
    """Draft the email back to the requester. Only blockers are asked about."""
    asks = []
    for f in findings:
        if f.severity == "Blocker" and f.fix and f.fix not in asks:
            asks.append(f.fix)
    first = str(req.get("requester_name") or "").split(" ")[0] or "there"
    ref = req.get("work_order") or "no work order given"
    customer = str(req.get("customer_name") or req.get("customer_account") or "the customer").rstrip(".")
    subject = f"Information needed: billing request {req['request_id']} ({ref})"
    body = (
        f"Hi {first},\n\n"
        f"Thanks for sending billing request {req['request_id']} for {customer}. "
        f"Before we can bill it, we need the following:\n\n"
        + "\n".join(f"{i}. {a}" for i, a in enumerate(asks, 1))
        + "\n\nYou can reply to this email with the details. "
        "We will bill the request as soon as we have them.\n\n"
        f"Thank you,\n{sender}\nBilling Team"
    )
    return subject, body
