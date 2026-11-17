"""Excel workbook of a client's transactions, for review or the client's file."""

from __future__ import annotations

import io
import json

from . import db
from .util import from_iso

INR_FORMAT = '[>=10000000]##\\,##\\,##\\,##0.00;[>=100000]##\\,##\\,##0.00;##,##0.00'
STATUS_LABELS = {"review": "Needs review", "ready": "Ready", "skipped": "Skipped", "duplicate": "Duplicate",
                 "posted": "Posted to Tally", "exported": "Exported to XML"}
CHECK_LABELS = {"ok": "Matches balance", "flipped": "Matches balance (column corrected)",
                "corrected": "Fixed from balances", "mismatch": "Doesn't match balance", "unchecked": "Not checked",
                "nobalance": "No balance on statement", "datecheck": "Check the date (read from a scan)"}


def workbook(conn, client_id: int, statement_id: int | None = None, account_id: int | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    client = db.client(conn, client_id)
    accounts = {a["id"]: a for a in db.accounts(conn, client_id)}
    rows = db.txns(conn, client_id, account_id=account_id, statement_id=statement_id)
    from .service import mapper_for

    mapper = mapper_for(conn, client_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"
    head = ["Date", "Value date", "Account", "Narration", "Ref / Cheque", "Debit", "Credit", "Balance",
            "Balance check", "Party", "Ledger", "Voucher", "Status", "Note"]
    ws.append(head)
    bold = Font(bold=True)
    fill = PatternFill("solid", fgColor="EEF2F0")
    for c in ws[1]:
        c.font = bold
        c.fill = fill
    for r in rows:
        acc = accounts.get(r["account_id"])
        vt = mapper.voucher_role(r["ledger"], r["direction"]).title() if r["ledger"] and r["direction"] else ""
        ws.append([
            from_iso(r["date"]), from_iso(r["value_date"]), acc["label"] if acc else "", r["narration"], r["ref"],
            r["amount"] / 100 if r["direction"] == "debit" else None,
            r["amount"] / 100 if r["direction"] == "credit" else None,
            r["balance"] / 100 if r["balance"] is not None else None,
            CHECK_LABELS.get(r["check_status"], r["check_status"]), r["party"], r["ledger"], vt,
            STATUS_LABELS.get(r["status"], r["status"]), r["check_note"] or r["map_note"],
        ])
    widths = [11, 11, 18, 60, 18, 14, 14, 15, 22, 24, 26, 10, 16, 40]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row[0:2]:
            c.number_format = "DD-MM-YYYY"
        for c in row[5:8]:
            c.number_format = INR_FORMAT
        row[3].alignment = Alignment(wrap_text=False)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    sm = wb.create_sheet("Statements")
    sm.append(["Account", "File", "From", "To", "Opening", "Closing", "Rows", "Balance check", "Notes"])
    for c in sm[1]:
        c.font = bold
        c.fill = fill
    for s in db.statements(conn, client_id):
        if statement_id and s["id"] != statement_id:
            continue
        if account_id and s["account_id"] != account_id:
            continue
        sm.append([s["account_label"], s["filename"], from_iso(s["period_from"]), from_iso(s["period_to"]),
                   s["opening"] / 100 if s["opening"] is not None else None,
                   s["closing"] / 100 if s["closing"] is not None else None, s["rows"],
                   {"verified": "Every row matches", "partial": "Some rows need a look",
                    "unverified": "No balances to check"}.get(s["status"], s["status"]),
                   " ".join(json.loads(s["warnings"] or "[]"))])
    for i, w in enumerate([20, 34, 11, 11, 15, 15, 7, 22, 80], start=1):
        sm.column_dimensions[get_column_letter(i)].width = w
    for row in sm.iter_rows(min_row=2):
        for c in row[2:4]:
            c.number_format = "DD-MM-YYYY"
        for c in row[4:6]:
            c.number_format = INR_FORMAT
    wb.properties.title = f"{client['name']} - bank transactions"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
