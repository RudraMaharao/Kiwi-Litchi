import hashlib
import ipaddress
import json
import os
import re
import urllib.request
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit, urlencode


class UserError(ValueError):
    pass


def money(value, blank=0):
    """Convert rupees to paise exactly; reject ambiguous or fractional paise."""
    if value is None or str(value).strip() in ("", "-", "—"):
        return blank
    s = str(value).strip().replace(",", "").replace("₹", "")
    s = re.sub(r"^(?:INR|Rs\.?)\s*", "", s, flags=re.I)
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    suffix = re.search(r"\s*(DR|CR)\.?$", s, re.I)
    if suffix:
        neg = suffix[1].upper() == "DR"
        s = s[:suffix.start()].strip()
    try:
        n = Decimal(s) * 100
        if not n.is_finite() or n != n.to_integral_value() or abs(n) > 9_000_000_000_000_000:
            raise UserError("Amount must be finite, within range, and have at most two decimals")
        return -abs(int(n)) if neg else int(n)
    except InvalidOperation as e:
        raise UserError(f"Cannot read amount: {value!r}") from e


def rupees(paise):
    sign = "-" if paise < 0 else ""
    n = abs(int(paise))
    return f"{sign}{n // 100}.{n % 100:02d}"


def iso_date(value):
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    raise UserError(f"Cannot read date {value!r}; use DD/MM/YYYY or YYYY-MM-DD")


def normal(text):
    return " ".join(re.findall(r"[a-z0-9]+", str(text).lower()))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def data_home():
    return Path(os.environ.get("KIWI_DATA_DIR", str(Path.home() / ".local/share/kiwi-litchi"))).expanduser().resolve()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def local_url(url, allow_lan=False):
    u = urlsplit(url)
    if u.scheme != "http" or u.username or u.password or u.query or u.fragment:
        raise UserError("Use a local http URL with no credentials, query or fragment")
    host = u.hostname
    if host == "localhost":
        return url.rstrip("/")
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError as e:
        raise UserError("Use localhost or a literal local IP address") from e
    allowed = ip.is_loopback or (allow_lan and (ip in ipaddress.ip_network("10.0.0.0/8") or ip in ipaddress.ip_network("172.16.0.0/12") or ip in ipaddress.ip_network("192.168.0.0/16") or ip in ipaddress.ip_network("100.64.0.0/10")))
    if not allowed:
        raise UserError("Remote/cloud endpoints are disabled")
    return url.rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise UserError("Local service redirected the request; refused")


def http(url, payload=None, method=None, xml=False, timeout=180, allow_lan=False, query=None):
    local_url(url, allow_lan)
    if query: url += '?' + urlencode(query)
    body = payload if xml else (json.dumps(payload).encode() if payload is not None else None)
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": "application/xml" if xml else "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=timeout) as res:
        raw = res.read(50 * 1024 * 1024 + 1)
    if len(raw) > 50 * 1024 * 1024:
        raise UserError("Service response exceeds 50 MB")
    return raw if xml else json.loads(raw)
