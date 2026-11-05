"""Synthetic workflow data: eight weeks of billing requests for the live demo.

All names, accounts and amounts are fictional. The customer master is the
Customers sheet of the Version 1 workbook, so account numbers agree across the
reports and the workflow. The history is simulated with the same functions the
app uses, so every status, follow-up and batch went through the real checks.
The workflow dates move with today's date; the Version 1 reports stay fixed
at 30 Sep 2026.
"""
from __future__ import annotations

import random
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

from workflow import rules
from workflow import store

CUSTOMER_FILE = Path(__file__).resolve().parent.parent / "data" / "billing_sample_data.xlsx"
ANALYSTS = ["Analyst 1", "Analyst 2", "Analyst 3"]
REQUESTERS = {
    "Lines": ["Dana Ellis", "Omar Haddad"], "Claims": ["Priya Nair", "Ben Carter"],
    "Forestry": ["Lucas Moreau"], "Field Operations": ["Grace Liu"], "Joint Use": ["Hannah Scott"],
    "Customer Connections": ["Ravi Mehta", "Elena Rossi"],
}
TEAM_CATEGORIES = {
    "Lines": ["Customer-Requested Work", "Third-Party Damage Recovery"],
    "Claims": ["Third-Party Damage Recovery"],
    "Forestry": ["Customer-Requested Work", "Miscellaneous"],
    "Field Operations": ["Miscellaneous", "Connection & Capital Contributions"],
    "Joint Use": ["Joint-Use Pole Attachments"],
    "Customer Connections": ["Connection & Capital Contributions", "Customer-Requested Work"],
}
TEAM_WEIGHTS = {"Lines": 22, "Claims": 26, "Forestry": 10, "Field Operations": 8, "Joint Use": 12, "Customer Connections": 22}
# Share of requests from each team that arrive with something missing or wrong
TEAM_DEFECT_RATE = {"Lines": 0.30, "Claims": 0.55, "Forestry": 0.35, "Field Operations": 0.20, "Joint Use": 0.30,
                    "Customer Connections": 0.20}
CATEGORY_CUSTOMERS = {
    "Third-Party Damage Recovery": ["Contractor", "Insurance Company", "Individual"],
    "Joint-Use Pole Attachments": ["Telecom"],
    "Customer-Requested Work": ["Individual", "Developer", "Municipality"],
    "Connection & Capital Contributions": ["Developer", "Municipality"],
    "Miscellaneous": ["Individual", "Contractor", "Municipality"],
}
AMOUNTS = {
    "Third-Party Damage Recovery": (1200, 60000), "Customer-Requested Work": (800, 40000),
    "Connection & Capital Contributions": (15000, 180000), "Miscellaneous": (150, 4000),
}
DESCRIPTIONS = {
    "Third-Party Damage Recovery": ["Pole replaced after vehicle strike", "Underground cable damaged during excavation",
                                    "Transformer replaced after collision", "Guy wire and anchor damaged by equipment"],
    "Customer-Requested Work": ["Temporary disconnect and reconnect for renovation", "Service relocation at customer request",
                                "Line clearance for tree removal", "Overhead to underground service conversion"],
    "Connection & Capital Contributions": ["New subdivision connection, phase 1", "Line extension for commercial site",
                                           "Capital contribution for upgraded service"],
    "Miscellaneous": ["Standby crew for customer event", "Meter base repair", "Engineering review fee"],
    "Joint-Use Pole Attachments": ["Annual pole attachment charges", "New attachments added this quarter"],
}


def load_customers() -> pd.DataFrame:
    """The Version 1 customer master: account number, name and type."""
    df = pd.read_excel(CUSTOMER_FILE, sheet_name="Customers", dtype={"CustomerID": str})
    return df.rename(columns={"CustomerID": "customer_account", "CustomerName": "customer_name",
                              "CustomerType": "customer_type"})[["customer_account", "customer_name", "customer_type"]]


def customer_lookup() -> dict:
    df = load_customers()
    return dict(zip(df.customer_account, df.customer_name))


def _business_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _add_business_days(d, n):
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _clean_request(rnd, team, cust_df, wo_counter, received_day, category=None, min_amount=0):
    cat = category or rnd.choice(TEAM_CATEGORIES[team])
    pool = cust_df[cust_df.customer_type.isin(CATEGORY_CUSTOMERS[cat])]
    c = pool.iloc[rnd.randrange(len(pool))]
    name = rnd.choice(REQUESTERS[team])
    done = received_day - timedelta(days=rnd.randint(1, 20))
    req = {
        "submitted_by_team": team, "requester_name": name,
        "requester_email": name.lower().replace(" ", ".") + "@example.com",
        "customer_account": c.customer_account, "customer_name": c.customer_name, "billing_category": cat,
        "work_order": f"WO-{wo_counter:06d}", "work_completed_date": done.isoformat(),
        "description": rnd.choice(DESCRIPTIONS[cat]), "cost_centre": rnd.choice(rules.COST_CENTRES),
    }
    if cat == "Joint-Use Pole Attachments":
        count = rnd.randint(40, 1600)
        req.update(attachment_count=count, total_amount=round(count * rules.POLE_ATTACHMENT_RATE, 2))
    else:
        lo, hi = AMOUNTS[cat]
        total = max(round(rnd.triangular(lo, hi, lo + (hi - lo) * 0.15), 2), round(min_amount + rnd.uniform(0, 20000), 2))
        labour = round(total * rnd.uniform(0.45, 0.7), 2)
        materials = round(total * rnd.uniform(0.1, 0.35), 2)
        req.update(labour=labour, materials=materials, equipment=round(total - labour - materials, 2), total_amount=total)
    if cat == "Third-Party Damage Recovery":
        req.update(incident_date=(done - timedelta(days=rnd.randint(0, 4))).isoformat(),
                   claim_reference=f"CLM-{rnd.randint(20000, 89999)}", supporting_docs="Yes")
    elif cat == "Customer-Requested Work":
        req["quote_reference"] = f"Q-{rnd.randint(10000, 99999)}"
    elif cat == "Connection & Capital Contributions":
        req["contract_number"] = f"CA-{rnd.randint(1000, 9999)}"
    return req


def _add_defects(rnd, req):
    bad = dict(req)
    cat = req["billing_category"]
    options = ["cost_centre", "bad_account", "bad_wo", "requester_email"]
    if cat == "Third-Party Damage Recovery":
        options += ["claim_reference", "claim_reference", "supporting_docs", "incident_date"]
    elif cat == "Joint-Use Pole Attachments":
        options += ["attachment_mismatch", "attachment_mismatch"]
    else:
        options += ["total_mismatch", "total_mismatch"]
    if cat == "Customer-Requested Work":
        options += ["quote_reference", "quote_reference"]
    if cat == "Connection & Capital Contributions":
        options += ["contract_number"]
    for d in rnd.sample(options, k=1 if rnd.random() < 0.7 else 2):
        if d == "bad_account":
            bad["customer_account"] = "C9" + req["customer_account"][2:]  # an account that does not exist
        elif d == "bad_wo":
            bad["work_order"] = req["work_order"].replace("WO-", "WO")
        elif d == "total_mismatch":
            bad["total_amount"] = round(req["total_amount"] + rnd.choice([100, 1000, -250, 90]), 2)
        elif d == "attachment_mismatch":
            bad["attachment_count"] = req["attachment_count"] + rnd.choice([-12, 8, 25])
        elif d == "supporting_docs":
            bad["supporting_docs"] = "No"
        elif d == "requester_email":
            bad["requester_email"] = None
        else:
            bad[d] = None
    return bad


def build_demo(conn, now: datetime, seed=11, weeks=8):
    """Simulate the last few weeks of requests, up to the end of the previous business day.

    The last simulated day leaves work in every stage: a batch waiting for the billing
    system's confirmation, requests ready for the next batch, approvals and follow-ups.
    """
    rnd = random.Random(seed)
    cust_df = load_customers()
    customers = dict(zip(cust_df.customer_account, cust_df.customer_name))
    last = now.date() - timedelta(days=1)
    while last.weekday() >= 5:
        last -= timedelta(days=1)
    start = last - timedelta(weeks=weeks)
    wo = 410_200
    clean_versions, replies, earlier = {}, {}, []
    pending_batch = None

    def at(day, hour, minute=0):
        return datetime.combine(day, time(hour, minute))

    def confirm(batch_id, day):
        conf = store.batch_file(conn, batch_id)
        conf = pd.DataFrame({"Reference": conf["Reference"],
                             "Invoice Number": [f"9{rnd.randint(1000000, 9999999)}" for _ in range(len(conf))],
                             "Invoice Amount": conf["Amount"]})
        if rnd.random() < 0.35 and len(conf) > 2:  # an occasional keying error in the billing system
            i = rnd.randrange(len(conf))
            conf.loc[i, "Invoice Amount"] = _keying_error(conf.loc[i, "Invoice Amount"])
        recon = store.reconcile(conn, batch_id, conf)
        store.confirm_batch(conn, batch_id, recon, rnd.choice(ANALYSTS), at(day, 9, 30))
        for r in recon[recon.result != "Matched"].itertuples():
            store.resolve_exception(conn, r.request_id, str(r.invoice_number), r.total_amount, rnd.choice(ANALYSTS),
                                    at(day, 11, 0), "Invoice amount corrected in billing system")

    for day in _business_days(start, last):
        # 1. Yesterday's batch is confirmed against the billing system first thing
        if pending_batch:
            confirm(pending_batch, day)
            pending_batch = None

        # 2. New requests arrive through the morning
        arrivals = sorted(at(day, rnd.randint(8, 11), rnd.choice([5, 20, 35, 50]))
                          for _ in range(5 if day == last else rnd.choice([2, 3, 3, 4])))
        for moment in arrivals:
            # 3. On the last day the batch goes at 11:00, so later work waits for the next one
            if day == last and pending_batch is None and moment.hour >= 11:
                pending_batch, _ = store.create_batch(conn, rnd.choice(ANALYSTS), at(day, 11, 0))
            team = rnd.choices(list(TEAM_WEIGHTS), list(TEAM_WEIGHTS.values()))[0]
            wo += rnd.randint(1, 40)
            large = day == last and moment == arrivals[-1]  # one large request still waiting for approval
            if large:
                team = "Customer Connections"
            clean = _clean_request(rnd, team, cust_df, wo, day, category="Connection & Capital Contributions" if large else None,
                                   min_amount=rules.APPROVAL_LIMIT + 10000 if large else 0)
            sent, duplicate = clean, False
            if large:
                pass
            elif earlier and rnd.random() < 0.03:  # the same work sent twice
                sent, duplicate = dict(rnd.choice(earlier)), True
            elif rnd.random() < TEAM_DEFECT_RATE[team]:
                sent = _add_defects(rnd, clean)
            source = rnd.choices(["Email", "Spreadsheet", "Intake form"], [6, 3, 1])[0]
            rid, _ = store.add_request(conn, sent, source, rnd.choice(ANALYSTS), moment, customers)
            clean_versions[rid] = None if duplicate else clean  # None: nothing to fix, it gets cancelled
            if not duplicate:
                earlier.append(clean)

        if day == last and pending_batch is None:
            pending_batch, _ = store.create_batch(conn, rnd.choice(ANALYSTS), at(day, 11, 0))

        # 4. Follow-ups, reminders and replies
        for req in store.all_requests(conn):
            if req["status"] != "Needs information":
                continue
            rid = req["request_id"]
            moment = at(day, 13, rnd.choice([0, 15, 30]))
            if not req["followups_sent"]:
                store.record_follow_up(conn, rid, req["received_by"], moment)
                replies[rid] = _add_business_days(day, rnd.choices([1, 2, 3, 5, 7], [30, 30, 20, 12, 8])[0])
            elif replies.get(rid) and replies[rid] <= day:
                fix_at = at(day, 15, rnd.choice([0, 20, 40]))
                if clean_versions.get(rid) is None:
                    store.cancel(conn, rid, req["received_by"], fix_at, "Duplicate: requester confirmed work was already billed")
                else:
                    store.update_request(conn, rid, clean_versions[rid], req["received_by"], fix_at, customers,
                                         note="Corrected after requester reply")
                replies.pop(rid)
            elif store.next_action(req, moment) == "Reminder due":
                store.record_follow_up(conn, rid, req["received_by"], moment)

        # 5. Supervisor approvals in the afternoon, for requests from earlier days
        for req in store.all_requests(conn):
            if req["status"] == "Awaiting approval" and req["received_at"][:10] < day.isoformat() and day != last:
                store.approve(conn, req["request_id"], store.SUPERVISOR, at(day, 14, 30), customers)

        # 6. Billing batches on Monday, Wednesday and Friday afternoons
        if day.weekday() in (0, 2, 4) and day != last:
            pending_batch, _ = store.create_batch(conn, rnd.choice(ANALYSTS), at(day, 16, 0))
    return conn


def _keying_error(amount: float) -> float:
    """Swap two digits, the most common data entry mistake."""
    s = f"{amount:.2f}"
    digits = [i for i, ch in enumerate(s) if ch.isdigit()]
    i = digits[0] if len(digits) < 3 else digits[1]
    j = i + 1 if s[i + 1].isdigit() else i - 1
    chars = list(s)
    chars[i], chars[j] = chars[j], chars[i]
    swapped = float("".join(chars))
    return swapped if swapped != amount else round(amount + 90, 2)


SAMPLE_EMAILS = {
    "Complete request (standard template)": """From: Grace Liu <grace.liu@example.com>
Subject: Billing request - meter base repair

Hi Billing team,

Please bill the following:

Submitting team: Field Operations
Customer account number: C0011
Customer name: Redrock Paving
Billing category: Miscellaneous
Work order number: WO-418850
Work completed date: {done}
Description of work: Meter base repair after contractor damage
Cost centre: 4320
Labour cost: 1,240.00
Materials cost: 385.50
Equipment cost: 210.00
Total amount to bill: 1,835.50

Thanks,
Grace Liu""",
    "Free-text email with missing details": """From: Priya Nair <priya.nair@example.com>
Subject: Damage recovery - Pinecrest Paving

Hi team,

Can you please bill Pinecrest Paving (account C0012) for the underground cable they damaged while
excavating on {incident_long}? Our crew finished the repair on {done_long} under work order WO-418902.

Costs came to $8,420.00 for labour, $2,915.75 for materials and $1,100.00 for equipment, so $12,435.75 in total.
Please charge it to cost centre 4210. I'll send the photos separately.

Thanks,
Priya Nair
Claims""",
    "Pole attachments with a calculation error": """From: Hannah Scott <hannah.scott@example.com>
Subject: Q4 pole attachments

Hello,

Submitting team: Joint Use
Customer account number: C0004
Customer name: Cedar Fibre Inc.
Billing category: Joint-Use Pole Attachments
Work order number: WO-418911
Work completed date: {done}
Description of work: New attachments added this quarter
Cost centre: 4510
Number of pole attachments: 214
Total amount to bill: 7,183.00

Regards,
Hannah Scott""",
}


def sample_email(name, today) -> str:
    done = today - timedelta(days=6)
    incident = done - timedelta(days=2)
    return SAMPLE_EMAILS[name].format(done=done.isoformat(), done_long=f"{done:%B} {done.day}",
                                      incident_long=f"{incident:%B} {incident.day}")


def sample_spreadsheet(today) -> pd.DataFrame:
    """A batch from one team, as it might arrive by email today, with a few typical problems."""
    rnd = random.Random(today.toordinal())
    cust_df = load_customers()
    rows = []
    for i in range(6):
        r = _clean_request(rnd, "Lines", cust_df, 418_950 + i * 3, today)
        rows.append(r)
    rows[1]["cost_centre"] = None
    rows[3]["total_amount"] = round(rows[3]["total_amount"] + 1000, 2) if rows[3].get("labour") else rows[3]["total_amount"]
    rows[4]["customer_account"] = "C9999"
    df = pd.DataFrame(rows).reindex(columns=rules.REQUEST_FIELDS)
    return df.rename(columns=rules.FIELD_LABELS)
