"""Suggest a Tally ledger for each bank line, and learn from the firm's choices.

Order of preference, most certain first:
  1. the firm's own rules ("narration contains SWIGGY -> Staff Welfare")
  2. what the firm chose last time for the same UPI ID or party
  3. transfers between the client's own bank accounts (Contra)
  4. standard bank items: cash withdrawals, charges, interest, tax payments
  5. a party ledger in Tally whose name matches the counterparty
  6. the suspense ledger, flagged for review
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .narration import NarrationInfo
from .util import party_key

BANK_GROUPS = {"bank accounts", "bank od a/c", "bank occ a/c"}
LOAN_GROUPS = {"loans (liability)", "secured loans", "unsecured loans", "bank od a/c", "bank occ a/c"}

DEFAULT_SETTINGS: dict = {
    "suspense_ledger": "Suspense A/c",
    "cash_ledger": "Cash",
    "category_ledgers": {
        "bank_charges": "Bank Charges",
        "interest_received": "Interest Received",
        "interest_paid": "Interest Paid",
        "tax_gst": "",
        "tax_income": "",
        "loan_emi": "",
        "salary": "Salary",
    },
    "voucher_types": {"payment": "Payment", "receipt": "Receipt", "contra": "Contra"},
    "date_basis": "txn",            # txn | value
    "bank_allocations": True,       # fill Tally's bank details (instrument no., bank date) so BRS is done
    "skip_incoming_own_transfers": True,
    "new_ledger_groups": {
        "debit_party": "Sundry Creditors",
        "credit_party": "Sundry Debtors",
        "expense": "Indirect Expenses",
        "income": "Indirect Incomes",
        "tax": "Duties & Taxes",
        "loan": "Unsecured Loans",
        "bank": "Bank Accounts",
        "suspense": "Suspense A/c",
    },
}

CATEGORY_GROUP = {
    "bank_charges": "expense", "interest_paid": "expense", "salary": "expense",
    "interest_received": "income", "tax_gst": "tax", "tax_income": "tax", "loan_emi": "loan",
}


def merged_settings(custom: dict | None) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_SETTINGS.items()}
    for k, v in (custom or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


@dataclass
class Ledger:
    name: str
    parent: str = ""
    kind: str = ""  # bank | cash | debtor | creditor | expense | income | tax | loan | suspense | other


def kind_from_ancestors(ancestors: list[str]) -> str:
    low = [a.lower().strip() for a in ancestors if a]
    if any(a in BANK_GROUPS for a in low):
        return "bank"
    if "cash-in-hand" in low:
        return "cash"
    if "sundry debtors" in low:
        return "debtor"
    if "sundry creditors" in low:
        return "creditor"
    if any(a in ("indirect expenses", "direct expenses", "purchase accounts", "expenses (indirect)",
                 "expenses (direct)") for a in low):
        return "expense"
    if any(a in ("indirect incomes", "direct incomes", "sales accounts", "income (indirect)", "income (direct)")
           for a in low):
        return "income"
    if "duties & taxes" in low or "duties and taxes" in low:
        return "tax"
    if any(a in LOAN_GROUPS for a in low):
        return "loan"
    if "suspense a/c" in low:
        return "suspense"
    return "other" if low else ""


@dataclass
class OwnAccount:
    account_id: int
    label: str
    number: str
    ledger: str

    @property
    def last4(self) -> str:
        digits = re.sub(r"\D", "", self.number)
        return digits[-4:] if len(digits) >= 4 else ""


@dataclass
class Rule:
    pattern: str
    ledger: str
    direction: str = "any"  # any | debit | credit
    id: int = 0

    def matches(self, narration: str, direction: str | None) -> bool:
        if self.direction in ("debit", "credit") and direction != self.direction:
            return False
        pat = self.pattern.strip()
        if not pat:
            return False
        if pat.lower().startswith("re:"):
            try:
                return re.search(pat[3:].strip(), narration, re.I) is not None
            except re.error:
                return False
        return pat.lower() in narration.lower()


@dataclass
class Suggestion:
    ledger: str
    source: str  # rule | memory | own | category | match | suspense | manual
    score: int
    note: str = ""
    skip: bool = False

    @property
    def sure(self) -> bool:
        return self.score >= 80


@dataclass
class ClientContext:
    client_name: str = ""
    ledgers: dict[str, Ledger] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)
    memory: dict[str, str] = field(default_factory=dict)
    settings: dict = field(default_factory=lambda: merged_settings({}))
    own_accounts: list[OwnAccount] = field(default_factory=list)


class Mapper:
    def __init__(self, ctx: ClientContext):
        self.ctx = ctx
        self.settings = merged_settings(ctx.settings)
        self._lower = {name.lower(): name for name in ctx.ledgers}
        self._party_choices = self._choices()

    # ------------------------------------------------------------ ledger facts

    def known(self, name: str) -> bool:
        return not self.ctx.ledgers or name.lower() in self._lower

    def canonical(self, name: str) -> str:
        return self._lower.get(name.lower(), name)

    def kind(self, name: str) -> str:
        led = self.ctx.ledgers.get(self.canonical(name))
        if led and led.kind:
            return led.kind
        if name.lower() == self.settings["cash_ledger"].lower() or name.lower() == "cash":
            return "cash"
        if any(a.ledger and a.ledger.lower() == name.lower() for a in self.ctx.own_accounts):
            return "bank"
        if name.lower() == self.settings["suspense_ledger"].lower():
            return "suspense"
        return ""

    def voucher_role(self, ledger: str, direction: str | None) -> str:
        if self.kind(ledger) in ("bank", "cash"):
            return "contra"
        return "receipt" if direction == "credit" else "payment"

    def _choices(self) -> dict[str, str]:
        out = {}
        for name, led in self.ctx.ledgers.items():
            if led.kind in ("bank", "cash", "tax", "suspense"):
                continue
            key = party_key(name)
            if key:
                out[key] = name
        return out

    # ------------------------------------------------------------ suggestion

    def suggest(self, narration: str, direction: str | None, info: NarrationInfo,
                account_id: int | None = None) -> Suggestion:
        s = self.settings
        suspense = s["suspense_ledger"]
        for rule in self.ctx.rules:
            if rule.matches(narration, direction):
                return self._checked(Suggestion(self.canonical(rule.ledger), "rule", 100, f"rule: {rule.pattern}"))
        for key in info.keys() or ([f"text:{_sig(narration)}"] if _sig(narration) else []):
            if key in self.ctx.memory:
                return self._checked(Suggestion(self.canonical(self.ctx.memory[key]), "memory", 95,
                                                "chosen before for this party"))
        own = self._own_transfer(narration, info, account_id)
        if own is not None:
            if direction == "credit" and s.get("skip_incoming_own_transfers", True) and own.ledger != suspense:
                own.skip = True
                own.note = "money in from the client's own account: post it from the other account's statement"
            return own
        cat = self._category(info, direction)
        if cat is not None:
            return cat
        match = self._match_party(info)
        if match is not None:
            return match
        note = "reversal: match it with the original entry" if info.category == "reversal" else "no match yet"
        return Suggestion(suspense, "suspense", 0, note)

    def _checked(self, sug: Suggestion) -> Suggestion:
        if not self.known(sug.ledger):
            sug.note = (sug.note + "; " if sug.note else "") + "not in Tally yet (will be created)"
            sug.score = min(sug.score, 75) if sug.source not in ("rule", "memory") else sug.score
        return sug

    def _own_transfer(self, narration: str, info: NarrationInfo, account_id: int | None) -> Suggestion | None:
        others = [a for a in self.ctx.own_accounts if a.account_id != account_id and a.ledger]
        digits_in_text = re.sub(r"\D", " ", narration).split()
        for acc in others:
            num = re.sub(r"\D", "", acc.number)
            if len(num) >= 6 and any(num == d or (len(d) >= 6 and num.endswith(d)) for d in digits_in_text):
                return Suggestion(acc.ledger, "own", 92, f"transfer with {acc.label}")
            if acc.last4 and info.account and info.account.endswith(acc.last4):
                return Suggestion(acc.ledger, "own", 88, f"transfer with {acc.label} (ends {acc.last4})")
        is_self = info.category == "own_transfer" or (
            info.party and self.ctx.client_name and party_key(info.party) == party_key(self.ctx.client_name))
        if is_self:
            if len(others) == 1:
                return Suggestion(others[0].ledger, "own", 80, f"own transfer, probably {others[0].label}")
            return Suggestion(self.settings["suspense_ledger"], "own", 40,
                              "transfer to the client's own account: pick the bank ledger")
        return None

    def _category(self, info: NarrationInfo, direction: str | None) -> Suggestion | None:
        s = self.settings
        cl = s["category_ledgers"]
        cat = info.category
        name, key = "", cat
        if cat == "cash_withdrawal" and direction == "debit":
            return Suggestion(self.canonical(s["cash_ledger"]), "category", 90, "cash withdrawal")
        if cat == "cash_deposit" and direction == "credit":
            return Suggestion(self.canonical(s["cash_ledger"]), "category", 90, "cash deposit")
        if cat == "bank_charges" and direction == "debit":
            name = cl.get("bank_charges", "")
        elif cat == "interest":
            key = "interest_received" if direction == "credit" else "interest_paid"
            name = cl.get(key, "")
        elif cat in ("tax_gst", "tax_income", "salary"):
            name = cl.get(cat, "")
        elif cat == "loan_emi" and direction == "debit":
            name = cl.get("loan_emi", "")
            if not name:
                match = self._match_party(info)
                if match is not None:
                    match.note = "loan EMI: " + match.note
                    return match
        else:
            return None
        labels = {"bank_charges": "bank charges", "interest_received": "interest received",
                  "interest_paid": "interest paid", "tax_gst": "GST payment", "tax_income": "income tax / TDS",
                  "salary": "salary", "loan_emi": "loan EMI"}
        if not name:
            return Suggestion(s["suspense_ledger"], "category", 30,
                              f"{labels.get(key, key)}: choose a ledger once in Settings and it's used every time")
        sug = Suggestion(self.canonical(name), "category", 85, labels.get(key, key))
        if not self.known(name):
            sug.score = 70
            sug.note += "; not in Tally yet (will be created)"
        return sug

    def _match_party(self, info: NarrationInfo) -> Suggestion | None:
        if not info.party or not self._party_choices:
            return None
        key = party_key(info.party)
        if not key:
            return None
        if key in self._party_choices:
            return Suggestion(self._party_choices[key], "match", 90, "same name as a Tally ledger")
        best = _best_match(key, list(self._party_choices))
        if best is None:
            return None
        cand, score = best
        name = self._party_choices[cand]
        if score >= 92:
            return Suggestion(name, "match", 84, f"name matches '{name}' ({score:.0f}%)")
        if score >= 82:
            return Suggestion(name, "match", 62, f"close to '{name}' ({score:.0f}%): check")
        return None

    def new_ledger_group(self, ledger: str, direction: str | None, source: str, note: str) -> str:
        groups = self.settings["new_ledger_groups"]
        if ledger.lower() == self.settings["suspense_ledger"].lower():
            return groups["suspense"]
        if any(a.ledger and a.ledger.lower() == ledger.lower() for a in self.ctx.own_accounts):
            return groups["bank"]
        if ledger.lower() == self.settings["cash_ledger"].lower():
            return "Cash-in-Hand"
        for cat, kind in CATEGORY_GROUP.items():
            if self.settings["category_ledgers"].get(cat, "").lower() == ledger.lower():
                return groups[kind]
        return groups["credit_party"] if direction == "credit" else groups["debit_party"]


def _sig(narration: str) -> str:
    from .narration import signature

    return signature(narration)


def memory_keys(narration: str, info: NarrationInfo) -> list[str]:
    keys = info.keys()
    if not keys:
        sig = _sig(narration)
        if sig:
            keys = [f"text:{sig}"]
    return keys


def _best_match(query: str, choices: list[str]) -> tuple[str, float] | None:
    try:
        from rapidfuzz import fuzz, process

        res = process.extractOne(query, choices, scorer=fuzz.token_set_ratio, score_cutoff=80)
        if res is None:
            return None
        cand, score = res[0], res[1]
        # token_set_ratio is generous with subsets ('gupta' vs 'gupta electricals'); temper with plain ratio
        plain = fuzz.ratio(query, cand)
        return cand, (score * 0.6 + plain * 0.4) if plain < score else score
    except ImportError:  # pragma: no cover
        import difflib

        best = difflib.get_close_matches(query, choices, n=1, cutoff=0.8)
        if not best:
            return None
        return best[0], difflib.SequenceMatcher(None, query, best[0]).ratio() * 100
