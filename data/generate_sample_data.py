"""Generate the synthetic billing and receivables sample data used by the app. All data is fictional."""
import random
from datetime import date, timedelta
import pandas as pd
from pathlib import Path

random.seed(29)
AS_OF = date(2026, 9, 30)
START = date(2025, 1, 1)
OUT = Path(__file__).parent / "billing_sample_data.xlsx"

REGIONS = ["Central", "Eastern", "Northern", "Western", "Southern"]
CATEGORIES = {
    # name: (amount low, high, share, customer types, base pay probability, dispute prob)
    "Third-Party Damage Recovery": (1500, 85000, 0.30, ["Contractor", "Individual", "Insurance Company"], 0.70, 0.18),
    "Joint-Use Pole Attachments": (5000, 120000, 0.20, ["Telecom"], 0.95, 0.05),
    "Customer-Requested Work": (800, 45000, 0.25, ["Individual", "Developer", "Municipality"], 0.88, 0.08),
    "Connection & Capital Contributions": (10000, 250000, 0.15, ["Developer", "Municipality"], 0.92, 0.06),
    "Miscellaneous": (100, 5000, 0.10, ["Individual", "Contractor", "Municipality"], 0.80, 0.07),
}
FIRST = ["Northshore", "Lakeview", "Maple", "Pinecrest", "Riverbend", "Granite", "Summit", "Birchwood", "Clearwater", "Redrock",
         "Silverline", "Ironwood", "Bluewater", "Highland", "Cedar", "Stonegate", "Westbrook", "Oakridge", "Harbour", "Evergreen"]
SUFFIX = {"Telecom": ["Telecom", "Networks", "Fibre Inc."], "Contractor": ["Excavating", "Construction Ltd.", "Paving"],
          "Developer": ["Developments", "Homes Inc.", "Properties"], "Municipality": ["Township", "County", "Municipality"],
          "Insurance Company": ["Insurance", "Mutual Insurance"], "Individual": [""]}
PEOPLE = ["A. Singh", "J. Chen", "M. Patel", "S. Brown", "R. Nguyen", "L. Martin", "K. Ali", "D. Wilson", "P. Roy", "T. Clarke"]
ANALYSTS = ["Analyst 1", "Analyst 2", "Analyst 3", "Analyst 4"]


def rand_date(a, b):
    return a + timedelta(days=random.randint(0, (b - a).days))


# Customers
customers = []
ctypes = ["Telecom"] * 8 + ["Contractor"] * 30 + ["Developer"] * 20 + ["Municipality"] * 15 + ["Insurance Company"] * 7 + ["Individual"] * 70
for i, t in enumerate(ctypes, 1):
    name = f"{random.choice(PEOPLE)} (Residential)" if t == "Individual" else f"{random.choice(FIRST)} {random.choice(SUFFIX[t])}"
    customers.append({"CustomerID": f"C{i:04d}", "CustomerName": name, "CustomerType": t, "Region": random.choice(REGIONS),
                      "CustomerSinceYear": random.randint(1995, 2025), "CreditLimit": random.choice([5000, 10000, 25000, 50000, 100000, 250000])})
cust_df = pd.DataFrame(customers)
by_type = cust_df.groupby("CustomerType")["CustomerID"].apply(list).to_dict()

# Billing requests -> invoices
requests, invoices, payments, cases, refunds = [], [], [], [], []
cat_names = list(CATEGORIES)
weights = [CATEGORIES[c][2] for c in cat_names]
inv_n = pay_n = case_n = 0
for r in range(1, 1701):
    cat = random.choices(cat_names, weights)[0]
    lo, hi, _, types, p_pay, p_disp = CATEGORIES[cat]
    cust = random.choice(by_type[random.choice([t for t in types if t in by_type])])
    region = cust_df.loc[cust_df.CustomerID == cust, "Region"].iat[0]
    work_done = rand_date(START, AS_OF - timedelta(days=5))
    submitted = work_done + timedelta(days=random.randint(0, 10))
    amount = round(random.triangular(lo, hi, lo + (hi - lo) * 0.2), 2)
    # Damage recovery takes longest to bill (investigation); a small backlog remains unbilled
    lag = random.randint(5, 25) + (random.randint(10, 45) if cat == "Third-Party Damage Recovery" else 0)
    invoice_date = submitted + timedelta(days=lag)
    status = "Invoiced" if invoice_date <= AS_OF else "Pending Invoice"
    requests.append({"RequestID": f"R{r:05d}", "CustomerID": cust, "Region": region, "BillingCategory": cat,
                     "WorkCompletedDate": work_done, "RequestSubmittedDate": submitted, "SubmittedByTeam":
                     random.choice(["Field Operations", "Forestry", "Lines", "Customer Connections", "Claims", "Joint Use"]),
                     "EstimatedAmount": amount, "RequestStatus": status})
    if status != "Invoiced":
        continue
    inv_n += 1
    inv_id = f"INV{inv_n:06d}"
    due = invoice_date + timedelta(days=30)
    disputed = random.random() < p_disp
    paid_prob = p_pay - (0.25 if disputed else 0)
    inv_status, paid_total = "Open", 0.0
    if random.random() < paid_prob:
        days_to_pay = max(1, int(random.gauss(38 if not disputed else 85, 18)))
        pay_date = invoice_date + timedelta(days=days_to_pay)
        if pay_date <= AS_OF:
            n_parts = 1 if random.random() < 0.85 else 2
            for k in range(n_parts):
                pay_n += 1
                part = round(amount / n_parts, 2)
                payments.append({"PaymentID": f"P{pay_n:06d}", "InvoiceID": inv_id,
                                 "PaymentDate": pay_date + timedelta(days=15 * k), "AmountPaid": part,
                                 "PaymentMethod": random.choice(["EFT", "Cheque", "Credit Card", "Wire"])})
                paid_total += part
            inv_status = "Paid"
    age = (AS_OF - invoice_date).days
    if inv_status == "Open" and age > 365 and random.random() < 0.35:
        inv_status = "Written Off"
    elif inv_status == "Open" and disputed:
        inv_status = "Disputed"
    invoices.append({"InvoiceID": inv_id, "RequestID": f"R{r:05d}", "CustomerID": cust, "Region": region,
                     "BillingCategory": cat, "WorkCompletedDate": work_done, "InvoiceDate": invoice_date, "DueDate": due,
                     "InvoiceAmount": amount, "AmountPaid": round(paid_total, 2), "Status": inv_status,
                     "AssignedAnalyst": random.choice(ANALYSTS)})
    # Collection cases for invoices more than 30 days past due and not paid
    if inv_status in ("Open", "Disputed", "Written Off") and (AS_OF - due).days > 30:
        case_n += 1
        opened = due + timedelta(days=random.randint(20, 45))
        promise = opened + timedelta(days=random.randint(7, 40)) if random.random() < 0.45 else None
        case_status = {"Written Off": "Write-Off Recommended", "Disputed": "Dispute Under Review"}.get(
            inv_status, random.choice(["Open", "Open", "Payment Plan", "Escalated"]))
        cases.append({"CaseID": f"CS{case_n:05d}", "InvoiceID": inv_id, "CaseOpenedDate": min(opened, AS_OF),
                      "ContactAttempts": random.randint(1, 8), "LastContactDate": min(opened + timedelta(days=random.randint(0, 60)), AS_OF),
                      "PromiseToPayDate": promise, "DisputeReason": random.choice(
                          ["Liability denied", "Amount questioned", "Insurance pending", "Wrong customer"]) if inv_status == "Disputed" else None,
                      "CaseStatus": case_status, "CaseOwner": random.choice(ANALYSTS)})

# Refunds (overpayments, cancelled work)
for f in range(1, 91):
    req = rand_date(START, AS_OF - timedelta(days=3))
    early = req < date(2025, 9, 1)  # process improvement: faster approvals after Sep 2025
    days = random.randint(25, 90) if early else random.randint(5, 30)
    appr = req + timedelta(days=days)
    refunds.append({"RefundID": f"RF{f:04d}", "CustomerID": random.choice(cust_df.CustomerID), "RefundReason":
                    random.choice(["Overpayment", "Cancelled work", "Duplicate payment", "Estimate exceeded actual cost"]),
                    "RequestDate": req, "ApprovalDate": appr if appr <= AS_OF else None,
                    "RefundAmount": round(random.uniform(150, 12000), 2)})

dates = pd.DataFrame({"Date": pd.date_range(START, date(2026, 12, 31))})
dates["Year"] = dates.Date.dt.year
dates["MonthNumber"] = dates.Date.dt.month
dates["MonthName"] = dates.Date.dt.strftime("%b")
dates["YearMonth"] = dates.Date.dt.strftime("%Y-%m")
dates["Quarter"] = "Q" + dates.Date.dt.quarter.astype(str)

readme = pd.DataFrame({"Notes": [
    "SYNTHETIC DATA - fictional, generated for a portfolio prototype. Not real customer or company data.",
    f"As-of date for aging and status: {AS_OF.isoformat()}",
    "Tables: Customers, BillingRequests, Invoices, Payments, CollectionCases, Refunds, Dates",
    "Relationships: Customers[CustomerID] 1-* Invoices/BillingRequests/Refunds; Invoices[InvoiceID] 1-* Payments and 1-* CollectionCases;",
    "BillingRequests[RequestID] 1-1 Invoices[RequestID]; Dates[Date] 1-* Invoices[InvoiceDate] (inactive links for DueDate, PaymentDate).",
    "BillingRequests with RequestStatus = 'Pending Invoice' are the unbilled backlog.",
    "Refund approvals were sped up from Sep 2025 (shows a process improvement trend).",
]})

with pd.ExcelWriter(OUT, engine="openpyxl", date_format="YYYY-MM-DD", datetime_format="YYYY-MM-DD") as xw:
    readme.to_excel(xw, sheet_name="README", index=False)
    for name, df in [("Customers", cust_df), ("BillingRequests", pd.DataFrame(requests)), ("Invoices", pd.DataFrame(invoices)),
                     ("Payments", pd.DataFrame(payments)), ("CollectionCases", pd.DataFrame(cases)),
                     ("Refunds", pd.DataFrame(refunds)), ("Dates", dates)]:
        for c in df.columns:
            if c.endswith("Date") or c == "Date":
                df[c] = pd.to_datetime(df[c])
        df.to_excel(xw, sheet_name=name, index=False)
        ws = xw.sheets[name]
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = max(12, min(40, max(len(str(c.value or "")) for c in col[:50]) + 2))
        ws.freeze_panes = "A2"
    xw.sheets["README"].column_dimensions["A"].width = 120

inv = pd.DataFrame(invoices)
print(len(customers), len(requests), len(inv), len(payments), len(cases), len(refunds))
print(inv.Status.value_counts().to_dict())
print(inv.groupby("BillingCategory").InvoiceAmount.sum().round(0).to_dict())
