"""Small helpers: money in paise, Indian date formats, text normalisation."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import tempfile
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------- money
# All money is held as integer paise so balance checks are exact.

_AMOUNT_RE = re.compile(
    r"""^
    (?P<lpar>\()?\s*
    (?P<sign>[-+−])?\s*
    (?:₹|RS\.?|INR)?\s*
    (?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?|\.\d{1,2})
    \s*(?P<tsign>-)?
    \s*(?P<rpar>\))?
    \s*(?P<drcr>\(?\s*(?:CR|DR)\s*\)?\.?)?
    $""",
    re.I | re.X,
)


class Amount:
    """A parsed amount cell: value in paise, optional Dr/Cr marker."""

    __slots__ = ("paise", "drcr", "decimals", "negative")

    def __init__(self, paise: int, drcr: str | None, decimals: bool, negative: bool):
        self.paise = paise
        self.drcr = drcr
        self.decimals = decimals
        self.negative = negative

    def signed(self) -> int:
        """Value with sign: Dr or a minus sign makes it negative."""
        if self.drcr == "DR" or self.negative:
            return -self.paise
        return self.paise

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Amount({self.paise}, {self.drcr}, neg={self.negative})"


def fix_ocr_digits(text: str) -> str:
    """Repair common OCR slips in a cell that is mostly digits."""
    text = text.strip(" ,;:'\"‘’`")
    core = re.sub(r"[\s,.₹()\-]", "", text)
    if not core:
        return text
    digits = sum(ch.isdigit() for ch in core)
    if digits / len(core) < 0.6:
        return text
    head, tail = text, ""
    m = re.search(r"(\(?\s*(?:CR|DR|Cr|Dr|cr|dr)\s*\)?\.?)$", text)
    if m:
        head, tail = text[: m.start()], text[m.start():]
    head = head.translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1"}))
    # '1,60,209:00' or '1,60,209,00': the last separator before two digits is the decimal point
    m = re.fullmatch(r"\s*([-+(]?)\s*([\d.,:;' ]*\d)[.,:;]\s?(\d{2})\s*([)]?)\s*", head)
    if m and re.search(r"\d", m.group(2)):
        whole = re.sub(r"[^\d]", "", m.group(2))
        head = f"{m.group(1)}{whole}.{m.group(3)}{m.group(4)}"
    return head + (" " + tail.strip() if tail.strip() else "")


def parse_amount(text: str | None, require_decimals: bool = False) -> Amount | None:
    """Parse '1,23,456.78', '5000.00 Cr', '(1,200.00)', '-45.5', '12,000.00Dr'."""
    if text is None:
        return None
    s = str(text).strip().replace(" ", " ")
    if not s or s in {"-", "--", "—", "NIL", "nil"}:
        return None
    s = s.replace(" ,", ",").replace(", ", ",")
    m = _AMOUNT_RE.match(s)
    if not m:
        return None
    num = m.group("num")
    decimals = "." in num
    if require_decimals and not decimals:
        return None
    whole, _, frac = num.replace(",", "").partition(".")
    frac = (frac + "00")[:2]
    paise = int(whole or "0") * 100 + int(frac or "0")
    negative = bool(m.group("sign") in ("-", "−") or m.group("tsign") or (m.group("lpar") and m.group("rpar")))
    drcr = None
    if m.group("drcr"):
        drcr = "CR" if "C" in m.group("drcr").upper() else "DR"
    return Amount(paise, drcr, decimals, negative)


def amount_from_number(value) -> int | None:
    """Excel numeric cell -> paise."""
    if value is None or value == "":
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def rupees(paise: int | None, sign: bool = False) -> str:
    """12345678 -> '1,23,456.78' (Indian grouping)."""
    if paise is None:
        return ""
    neg = paise < 0
    whole, frac = divmod(abs(int(paise)), 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    out = f"{s}.{frac:02d}"
    if neg:
        return "-" + out
    return ("+" + out) if sign else out


def plain_amount(paise: int) -> str:
    """Tally XML style: -1234.50"""
    neg = paise < 0
    whole, frac = divmod(abs(int(paise)), 100)
    return f"{'-' if neg else ''}{whole}.{frac:02d}"


# ---------------------------------------------------------------- dates

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sept|sep|oct|nov|dec)[a-z]*"
_TIME = r"(?:[\sT]+\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*(?:am|pm)?)?"

_DATE_PATTERNS = [
    # 01/04/2026, 1-4-26, 01.04.2026
    (re.compile(rf"^(\d{{1,2}})\s*[/\-.]\s*(\d{{1,2}})\s*[/\-.]\s*(\d{{2}}|\d{{4}}){_TIME}$", re.I), "dmy"),
    # 01 Apr 2026, 01-Apr-26, 1 April, 2026, 01Apr2026, 01/Apr/2026
    (re.compile(rf"^(\d{{1,2}})\s*[\s/\-.]?\s*{_MON}\s*[\s/\-.,]?\s*(\d{{2}}|\d{{4}}){_TIME}$", re.I), "dMy"),
    # 2026-04-01
    (re.compile(rf"^(\d{{4}})\s*[/\-.]\s*(\d{{1,2}})\s*[/\-.]\s*(\d{{1,2}}){_TIME}$", re.I), "ymd"),
    # Apr 01, 2026
    (re.compile(rf"^{_MON}\s*[\s.\-]\s*(\d{{1,2}})\s*,?\s*(\d{{4}}){_TIME}$", re.I), "Mdy"),
]


def _year(y: str) -> int:
    n = int(y)
    if len(y) == 2:
        return 2000 + n if n < 70 else 1900 + n
    return n


def parse_date(text) -> dt.date | None:
    """Day-first parsing of the date formats Indian banks print."""
    if text is None:
        return None
    if isinstance(text, dt.datetime):
        return text.date()
    if isinstance(text, dt.date):
        return text
    s = str(text).strip().strip(",").replace(" ", " ")
    s = re.sub(r"\s+", " ", s)
    if not s or len(s) > 32:
        return None
    for rx, kind in _DATE_PATTERNS:
        m = rx.match(s)
        if not m:
            continue
        try:
            if kind == "dmy":
                d, mo, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
            elif kind == "dMy":
                d, mo, y = int(m.group(1)), MONTHS[m.group(2).lower()[:3]], _year(m.group(3))
            elif kind == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                mo, d, y = MONTHS[m.group(1).lower()[:3]], int(m.group(2)), int(m.group(3))
            if not 1990 <= y <= 2100:
                return None
            return dt.date(y, mo, d)
        except (ValueError, KeyError):
            return None
    return None


def starts_with_date(text: str) -> tuple[dt.date | None, str]:
    """'01/04/2026 UPI-ABC' -> (date, 'UPI-ABC'). Handles '1 Apr 2026 ...'."""
    s = str(text).strip()
    m = re.match(
        rf"^(\d{{1,2}}\s*[/\-.]\s*\d{{1,2}}\s*[/\-.]\s*\d{{2,4}}|\d{{1,2}}\s*[\s/\-.]?\s*{_MON}\s*[\s/\-.,]?\s*\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}})\b",
        s,
        re.I,
    )
    if not m:
        return None, s
    d = parse_date(m.group(1))
    if not d:
        return None, s
    return d, s[m.end():].strip()


def iso(d: dt.date | None) -> str:
    return d.isoformat() if d else ""


def from_iso(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def nice_date(s: str | dt.date | None) -> str:
    d = s if isinstance(s, dt.date) else from_iso(s)
    return d.strftime("%d %b %Y") if d else ""


def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


# ---------------------------------------------------------------- text

def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


def norm_key(s: str) -> str:
    """For comparing labels: lower case, punctuation to spaces."""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^a-z0-9%]+", " ", s)
    return s.strip()


LEGAL_SUFFIXES = re.compile(
    r"\b(pvt|private|ltd|limited|llp|inc|co|company|corp|corporation|the|m s|ms|and|opc)\b"
)


def party_key(name: str) -> str:
    """'M/s. ABC Traders Pvt. Ltd.' -> 'abc traders'."""
    s = norm_key(name).replace("m s ", "ms ")
    s = LEGAL_SUFFIXES.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def short_hash(*parts) -> str:
    h = hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8"))
    return h.hexdigest()[:16]


def write_atomic(path: Path, data: str | bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def safe_filename(name: str, fallback: str = "file") -> str:
    name = re.sub(r"[^\w.\- ]+", "_", name or "").strip(" ._")
    return name[:120] or fallback


def clean_ocr_text(text: str) -> str:
    """Undo OCR habits that break party matching: 'name @ybl' -> 'name@ybl', 'SBINO001234' -> 'SBIN0001234'."""
    text = re.sub(r"\s*@\s*", "@", text)
    text = re.sub(r"\b([A-Z]{4})[O](?=[A-Z0-9]{6}\b)", r"\g<1>0", text)
    return norm_space(text)
