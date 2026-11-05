"""The workflow half of what the assistant is told.

Every figure is worked out here in Python from the visitor's tracker. The model
only reads this summary and puts it into words. One labelled line per fact, so
even a small model reads each value with the right label.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from workflow import rules
from workflow import store

def _days(text, now):
    return (now.date() - datetime.strptime(text[:10], "%Y-%m-%d").date()).days


def _ago(n):
    return "today" if n == 0 else f"{n} day{'s' if n != 1 else ''} ago"


def build_context(conn, customers: dict, now: datetime) -> str:
    reqs = store.table(conn, "SELECT * FROM requests")
    checks = store.table(conn, "SELECT * FROM checks_log WHERE run_no = 1")
    events = store.table(conn, "SELECT * FROM events")
    open_reqs = reqs[reqs.status.isin(rules.OPEN_STATUSES)].sort_values("received_at")
    records = open_reqs.to_dict("records")
    actions = [store.next_action(r, now) for r in records]

    lines = [f"Today: {now:%A %d %B %Y}"]

    counts = reqs.status.value_counts()
    lines.append("\nRequests by status:")
    lines += [f"- {s}: {counts.get(s, 0)}" for s in rules.OPEN_STATUSES + ["Billed", "Cancelled"]]

    lines.append("\nNext actions waiting:")
    lines += [
        f"- Follow-up emails to send: {actions.count('Send follow-up')}",
        f"- Reminders due (no reply after {store.REMINDER_AFTER_DAYS} days): {actions.count('Reminder due')}",
        f"- Requests waiting for supervisor approval: {actions.count('Supervisor approval')}",
        f"- Requests ready to add to a billing batch: {actions.count('Add to billing batch')}",
        f"- Requests sent to billing, waiting for confirmation: {actions.count('Confirm with billing system')}",
        f"- Reconciliation exceptions to resolve: {actions.count('Check exception')}",
    ]

    lines.append("\nOpen requests, oldest first:")
    for r, action in zip(records, actions):
        problems = [f.message for f in store.findings_for(conn, r, customers, now.date())
                    if f.severity == "Blocker" or (f.severity == "Approval" and not r.get("approved_by"))]
        if r.get("approved_by"):
            problems.append(f"approved by {r['approved_by']}")
        if r.get("exception"):
            problems.append("Reconciliation exception: " + r["exception"])
        amount = f"${r['total_amount']:,.2f}" if pd.notna(r["total_amount"]) else "amount not given"
        lines.append(
            f"- {r['request_id']} | team: {r['submitted_by_team'] or 'not given'} | customer: "
            f"{r['customer_name'] or 'not given'} | category: {r['billing_category'] or 'not given'} | amount: {amount} | "
            f"status: {r['status']} | received {_ago(_days(r['received_at'], now))} | next action: {action} | "
            f"follow-ups sent: {int(r['followups_sent'] or 0)} | notes: {'; '.join(problems) or 'none'}")
    if not records:
        lines.append("- none")

    billed = reqs[reqs.status == "Billed"]
    days = (pd.to_datetime(billed.billed_at) - pd.to_datetime(billed.received_at)).dt.total_seconds() / 86400
    blockers = checks[checks.severity == "Blocker"]
    first = reqs[reqs.first_pass_clean.notna()]
    lines.append(f"\nLast {max(1, (now - pd.to_datetime(reqs.received_at).min()).days // 7)} weeks:")
    lines += [
        f"- Requests received: {len(reqs)}",
        f"- Complete on first submission: {first.first_pass_clean.mean():.0%}" if len(first) else "- Complete on first submission: -",
        f"- Median days from request to invoice: {days.median():.1f}" if len(days) else "- Median days to invoice: -",
        f"- Problems caught at intake before billing: {len(blockers)}",
        f"- Keying errors caught at reconciliation: {(events.action == 'Reconciliation exception').sum()}",
    ]

    def label(row):
        return ("Missing " + rules.FIELD_LABELS[row.field].lower()) if row.rule_id == "REQ" else rules.PROBLEM_LABEL[row.rule_id]

    if len(blockers):
        blockers = blockers.assign(problem=blockers.apply(label, axis=1))
        lines.append("\nMost common problems at intake:")
        lines += [f"- {p}: {n}" for p, n in blockers.problem.value_counts().head(6).items()]
        team_of = reqs.set_index("request_id").submitted_by_team
        blockers = blockers.assign(team=blockers.request_id.map(team_of))
    lines.append("\nComplete on first submission by submitting team, lowest first:")
    by_team = first.groupby("submitted_by_team").first_pass_clean.agg(["mean", "count"]).sort_values("mean")
    for team, row in by_team.iterrows():
        top = blockers[blockers.team == team].problem.value_counts() if len(blockers) else pd.Series(dtype=int)
        common = f"; most common problem: {top.index[0]} ({top.iloc[0]})" if len(top) else ""
        lines.append(f"- {team}: {row['mean']:.0%} of {int(row['count'])} requests{common}")
    return "\n".join(lines)
