"""
Tally Sync Agent v0.2  (standard library only, so it also runs in a bare container)

First run : pairs with the server (merchant clicks Allow in the browser).
Every cycle: reports open Tally companies -> reads which ones the merchant enabled
             on the dashboard -> syncs only those (masters, vouchers, deletion check).

    python agent.py            # normal (tray icon if pystray is installed)
    python agent.py --once     # one sync cycle, console only (testing)
    python agent.py --no-tray  # loop in the console
"""
import argparse
import datetime as dt
import hashlib
import json
import logging
import logging.handlers
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

VERSION = "0.2.2"
IS_WIN = os.name == "nt"
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))      # bundled files
DATA_DIR = (Path(os.environ.get("APPDATA", Path.home())) / "TallySync") if IS_WIN \
    else Path(os.environ.get("TALLYSYNC_HOME", Path.home() / ".tallysync"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
TOKEN_FILE = DATA_DIR / "token.bin"
HASH_FILE = DATA_DIR / "sent_hashes.json"      # fingerprints of vouchers already uploaded (older Tally)
BATCH_SIZE = 200

log = logging.getLogger("agent")
log.setLevel(logging.INFO)
_fh = logging.handlers.RotatingFileHandler(DATA_DIR / "agent.log", maxBytes=2_000_000,
                                           backupCount=3, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_fh)
if sys.stdout is not None:                       # no console in --noconsole builds
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_sh)

STATUS = "Starting..."
STOP = threading.Event()
PAUSED = threading.Event()


class Unauthorized(Exception): ...
class ApiError(Exception): ...
class TallyError(Exception): ...


def set_status(s):
    global STATUS
    STATUS = s
    log.info(s)


def notify(title, msg):
    """Pop-up on Windows (non-blocking); log elsewhere."""
    log.warning("%s: %s", title, msg)
    if IS_WIN:
        import ctypes
        threading.Thread(target=lambda: ctypes.windll.user32.MessageBoxW(0, msg, title, 0x40),
                         daemon=True).start()


# ---------------------------------------------------------------- config / token / state
def load_config():
    cfg = {"tally_url": "http://localhost:9000", "api_url": "", "poll_seconds": 300,
           "since": dt.date(dt.date.today().year - 3, 4, 1).isoformat()}
    for f in (APP_DIR / "build_config.json", DATA_DIR / "config.json"):   # later overrides earlier
        if f.exists():
            cfg.update(json.loads(f.read_text(encoding="utf-8-sig")))
    if os.environ.get("TALLYSYNC_API"):
        cfg["api_url"] = os.environ["TALLYSYNC_API"]
    cfg["api_url"] = cfg["api_url"].rstrip("/")
    return cfg


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("DPAPI failed")
    out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return out


def save_token(token: str):
    raw = token.encode()
    TOKEN_FILE.write_bytes(_dpapi(raw, True) if IS_WIN else raw)   # Windows: encrypted for this user
    if not IS_WIN:
        os.chmod(TOKEN_FILE, 0o600)


def load_token():
    if not TOKEN_FILE.exists():
        return ""
    try:
        raw = TOKEN_FILE.read_bytes()
        return (_dpapi(raw, False) if IS_WIN else raw).decode()
    except Exception:
        return ""


def clear_token():
    TOKEN_FILE.unlink(missing_ok=True)


def load_state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


_HASHES = None


def _hashes():
    global _HASHES
    if _HASHES is None:
        try:
            _HASHES = json.loads(HASH_FILE.read_text())
        except Exception:
            _HASHES = {}
    return _HASHES


def save_hashes():
    HASH_FILE.write_text(json.dumps(_hashes()))


# ---------------------------------------------------------------- HTTP to our server
def http_json(method, url, payload=None, token=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Agent-Version", VERSION)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise Unauthorized()
        raise ApiError(f"HTTP {e.code} on {url}: {e.read()[:200]!r}")


def api(cfg, method, path, payload=None, retries=5):
    for attempt in range(retries):
        try:
            return http_json(method, cfg["api_url"] + path, payload, cfg["token"])
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            wait = min(2 ** attempt, 30)
            log.warning("%s %s failed (%s). Retry in %ss", method, path, e, wait)
            if STOP.wait(wait):
                raise
    raise ApiError(f"could not reach server for {path}")


# ---------------------------------------------------------------- pairing
def pair(cfg) -> bool:
    start = http_json("POST", cfg["api_url"] + "/v1/pair/start",
                      {"hostname": socket.gethostname(), "version": VERSION})
    set_status(f"Approve this agent in your browser. Code: {start['user_code']}")
    try:
        webbrowser.open(start["verification_url"])
    except Exception:
        pass
    notify("Tally Sync", f"Approve this agent on the website.\nCode: {start['user_code']}\n"
                         f"If no page opened, go to: {start['verification_url']}")
    deadline = time.time() + start["expires_in"]
    while time.time() < deadline and not STOP.is_set():
        STOP.wait(start["interval"])
        p = http_json("POST", cfg["api_url"] + "/v1/pair/poll", {"device_code": start["device_code"]})
        if p["status"] == "approved":
            save_token(p["token"])
            cfg["token"] = p["token"]
            return True
        if p["status"] in ("denied", "expired", "invalid", "consumed"):
            set_status(f"Pairing {p['status']}.")
            return False
    return False


# ---------------------------------------------------------------- Tally access
_NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def sanitize(raw: bytes) -> str:
    """Tally sometimes emits illegal XML characters (e.g. &#4;). Strip them."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in raw[:20]:
        text = raw.decode("utf-16", errors="replace")          # some Tally versions reply in UTF-16
    else:
        text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return re.sub(r"&#(\d+);",
                  lambda m: "" if int(m.group(1)) < 32 and int(m.group(1)) not in (9, 10, 13) else m.group(0),
                  text)


def parse_xml(text: str) -> ET.Element:
    try:
        return ET.fromstring(text)
    except ET.ParseError:                                       # several top-level elements? wrap them
        body = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
        return ET.fromstring("<ROOT>" + body + "</ROOT>")


def tally_post(cfg, xml: str, timeout=300) -> ET.Element:
    req = urllib.request.Request(cfg["tally_url"], data=xml.encode("utf-8"),
                                 headers={"Content-Type": "text/xml"})
    try:
        with _NOPROXY.open(req, timeout=timeout) as r:
            return parse_xml(sanitize(r.read()))
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise TallyError(str(e))


def collection_xml(name, tally_type, fetch, company=None, from_date=None, to_date=None, formula=None):
    sv = "<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"
    if company:
        sv += f"<SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>"
    if from_date:
        sv += f"<SVFROMDATE>{from_date:%Y%m%d}</SVFROMDATE>"
    if to_date:
        sv += f"<SVTODATE>{to_date:%Y%m%d}</SVTODATE>"
    filt = f"<FILTER>{name}Filter</FILTER>" if formula else ""
    sysf = (f'<SYSTEM TYPE="Formulae" NAME="{name}Filter">{escape(formula)}</SYSTEM>' if formula else "")
    return f"""<ENVELOPE>
 <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>{name}</ID></HEADER>
 <BODY><DESC>
  <STATICVARIABLES>{sv}</STATICVARIABLES>
  <TDL><TDLMESSAGE>
   <COLLECTION NAME="{name}" ISMODIFY="No"><TYPE>{tally_type}</TYPE><FETCH>{escape(fetch)}</FETCH>{filt}</COLLECTION>
   {sysf}
  </TDLMESSAGE></TDL>
 </DESC></BODY>
</ENVELOPE>"""


def txt(el, tag):
    c = el.find(tag)
    return (c.text or "").strip() if c is not None and c.text else ""


def num(s):
    """'-45000.00' / '10 Nos' -> float, else None."""
    if not s:
        return None
    try:
        return float(s.split()[0].replace(",", ""))
    except ValueError:
        return None


def tdate(s):
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def _prime_list_companies(cfg):
    root = tally_post(cfg, collection_xml("AgentCompanies", "Company", "Name"), timeout=30)
    names = [c.get("NAME") or txt(c, "NAME") for c in root.iter("COMPANY")]
    return list(dict.fromkeys(n for n in names if n))


def _prime_fetch_ledgers(cfg, company):
    xml = collection_xml("AgentLedgers", "Ledger", "Name, Parent, OpeningBalance, ClosingBalance, GUID, AlterID", company)
    out = []
    for el in tally_post(cfg, xml).iter("LEDGER"):
        name = el.get("NAME") or txt(el, "NAME")
        if name:
            out.append({"guid": txt(el, "GUID") or name, "name": name, "parent": txt(el, "PARENT"),
                        "opening_balance": num(txt(el, "OPENINGBALANCE")),
                        "closing_balance": num(txt(el, "CLOSINGBALANCE")),
                        "alter_id": int(num(txt(el, "ALTERID")) or 0)})
    return out


def _prime_fetch_stock_items(cfg, company):
    xml = collection_xml("AgentStock", "StockItem",
                         "Name, Parent, BaseUnits, ClosingBalance, ClosingValue, GUID, AlterID", company)
    out = []
    for el in tally_post(cfg, xml).iter("STOCKITEM"):
        name = el.get("NAME") or txt(el, "NAME")
        if name:
            out.append({"guid": txt(el, "GUID") or name, "name": name, "parent": txt(el, "PARENT"),
                        "unit": txt(el, "BASEUNITS"), "closing_qty": num(txt(el, "CLOSINGBALANCE")),
                        "closing_value": num(txt(el, "CLOSINGVALUE")),
                        "alter_id": int(num(txt(el, "ALTERID")) or 0)})
    return out


VOUCHER_FETCH = ("Date, VoucherTypeName, VoucherNumber, PartyLedgerName, Narration, GUID, AlterID, "
                 "AllLedgerEntries.LedgerName, AllLedgerEntries.Amount, "
                 "AllInventoryEntries.StockItemName, AllInventoryEntries.Rate, "
                 "AllInventoryEntries.BilledQty, AllInventoryEntries.Amount")


def parse_voucher(v):
    ledger_entries, inv_entries = [], []
    for child in v:
        if child.tag in ("ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST"):
            ledger_entries.append({"ledger": txt(child, "LEDGERNAME"), "amount": num(txt(child, "AMOUNT"))})
        elif child.tag in ("ALLINVENTORYENTRIES.LIST", "INVENTORYENTRIES.LIST"):
            inv_entries.append({"item": txt(child, "STOCKITEMNAME"), "rate": txt(child, "RATE"),
                                "qty": txt(child, "BILLEDQTY"), "amount": num(txt(child, "AMOUNT"))})
    amounts = [abs(e["amount"]) for e in ledger_entries if e["amount"] is not None]
    return {"guid": txt(v, "GUID") or v.get("REMOTEID", ""), "alter_id": int(num(txt(v, "ALTERID")) or 0),
            "date": tdate(txt(v, "DATE")), "type": txt(v, "VOUCHERTYPENAME") or v.get("VCHTYPE", ""),
            "number": txt(v, "VOUCHERNUMBER"), "party": txt(v, "PARTYLEDGERNAME"),
            "narration": txt(v, "NARRATION"),
            "amount": round(sum(amounts) / 2, 2) if amounts else None,   # debits == credits
            "ledger_entries": ledger_entries, "inventory_entries": inv_entries,
            "raw": ET.tostring(v, encoding="unicode")}


def _prime_fetch_vouchers(cfg, company, from_date, to_date, min_alter_id=None):
    formula = f"$AlterID > {int(min_alter_id)}" if min_alter_id is not None else None
    xml = collection_xml("AgentVouchers", "Voucher", VOUCHER_FETCH, company, from_date, to_date, formula)
    vs = [parse_voucher(v) for v in tally_post(cfg, xml).iter("VOUCHER")]
    vs = [v for v in vs if v["guid"]]
    if min_alter_id is not None:                      # belt and braces
        vs = [v for v in vs if v["alter_id"] > min_alter_id]
    return vs


def _prime_fetch_voucher_guids(cfg, company, from_date, to_date):
    xml = collection_xml("AgentGuids", "Voucher", "GUID", company, from_date, to_date)
    return [txt(v, "GUID") for v in tally_post(cfg, xml).iter("VOUCHER") if txt(v, "GUID")]


# ---------------------------------------------------------------- older Tally (ERP 9) support
# ERP 9 only understands the classic "Export Data" request style. We detect which style the
# running Tally speaks (TallyPrime style first, then the classic one) and use it from then on.
def legacy_xml(report, company=None, from_date=None, to_date=None, extra=""):
    sv = "<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"
    if company:
        sv += f"<SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>"
    if from_date:
        sv += f'<SVFROMDATE TYPE="DATE">{from_date:%Y%m%d}</SVFROMDATE>'
    if to_date:
        sv += f'<SVTODATE TYPE="DATE">{to_date:%Y%m%d}</SVTODATE>'
    return ("<ENVELOPE><HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER><BODY><EXPORTDATA><REQUESTDESC>"
            f"<REPORTNAME>{report}</REPORTNAME><STATICVARIABLES>{sv}{extra}</STATICVARIABLES>"
            "</REQUESTDESC></EXPORTDATA></BODY></ENVELOPE>")


def list_companies(cfg):
    mode = cfg.get("tally_mode")
    if mode in (None, "prime"):
        names = _prime_list_companies(cfg)
        if names:
            cfg["tally_mode"] = "prime"
            return names
    if mode in (None, "legacy"):
        root = tally_post(cfg, legacy_xml("List of Companies"), timeout=30)
        names = [(c.text or "").strip() for c in root.iter("COMPANYNAME")
                 if (c.text or "").strip()]
        for company in root.iter("COMPANY"):
            name = company.get("NAME") or txt(company, "NAME")
            if name:
                names.append(name)
        names = list(dict.fromkeys(names))
        if names:
            if mode is None:
                log.info("Older Tally detected: using the classic 'Export Data' requests")
            cfg["tally_mode"] = "legacy"
            return names
    return []


def fetch_ledgers(cfg, company):
    if cfg.get("tally_mode") != "legacy":
        return _prime_fetch_ledgers(cfg, company)
    root = tally_post(cfg, legacy_xml("List of Accounts", company, extra="<ACCOUNTTYPE>Ledgers</ACCOUNTTYPE>"))
    out = []
    for el in root.iter("LEDGER"):
        name = el.get("NAME") or txt(el, "NAME")
        if name:
            out.append({"guid": txt(el, "GUID") or el.get("REMOTEID") or name, "name": name,
                        "parent": txt(el, "PARENT"),
                        "opening_balance": num(txt(el, "OPENINGBALANCE")),
                        "closing_balance": None,           # not part of the classic master export
                        "alter_id": int(num(txt(el, "ALTERID")) or 0)})
    return out


def fetch_stock_items(cfg, company):
    if cfg.get("tally_mode") != "legacy":
        return _prime_fetch_stock_items(cfg, company)
    try:
        root = tally_post(cfg, legacy_xml("List of Accounts", company,
                                          extra="<ACCOUNTTYPE>Stock Items</ACCOUNTTYPE>"))
    except (TallyError, ET.ParseError) as e:
        log.warning("[%s] could not read stock items (%s); continuing without them", company, e)
        return []
    out = []
    for el in root.iter("STOCKITEM"):
        name = el.get("NAME") or txt(el, "NAME")
        if name:
            out.append({"guid": txt(el, "GUID") or el.get("REMOTEID") or name, "name": name,
                        "parent": txt(el, "PARENT"), "unit": txt(el, "BASEUNITS"),
                        "closing_qty": None, "closing_value": None,   # needs a Stock Summary report (later)
                        "alter_id": int(num(txt(el, "ALTERID")) or 0)})
    return out


def fetch_vouchers(cfg, company, from_date, to_date, min_alter_id=None):
    if cfg.get("tally_mode") != "legacy":
        return _prime_fetch_vouchers(cfg, company, from_date, to_date, min_alter_id)
    root = tally_post(cfg, legacy_xml("Day Book", company, from_date, to_date), timeout=300)
    vs = [parse_voucher(v) for v in root.iter("VOUCHER")]
    return [v for v in vs if v["guid"]]


def fetch_voucher_guids(cfg, company, from_date, to_date):
    if cfg.get("tally_mode") != "legacy":
        return _prime_fetch_voucher_guids(cfg, company, from_date, to_date)
    return [v["guid"] for v in fetch_vouchers(cfg, company, from_date, to_date)]


# ---------------------------------------------------------------- sync logic
def post_vouchers(cfg, company, vouchers):
    for i in range(0, len(vouchers), BATCH_SIZE):
        chunk = vouchers[i:i + BATCH_SIZE]
        api(cfg, "POST", "/v1/ingest/vouchers",
            {"company": company, "batch_id": str(uuid.uuid4()),
             "max_alter_id": max(v["alter_id"] for v in chunk), "vouchers": chunk})


def post_changed(cfg, company, vouchers, save=True):
    """Upload only vouchers whose content differs from what we sent last time. Older Tally may give
    no usable AlterID, so a fingerprint of each voucher decides what changed. Returns how many were sent."""
    seen = _hashes().setdefault(company, {})
    todo = []
    for v in vouchers:
        fp = hashlib.sha1(v["raw"].encode("utf-8")).hexdigest()[:16]
        if seen.get(v["guid"]) != fp:
            todo.append((v, fp))
    if todo:
        post_vouchers(cfg, company, [v for v, _ in todo])      # raises on failure -> nothing marked as sent
        for v, fp in todo:
            seen[v["guid"]] = fp
        if save:
            save_hashes()
    return len(todo)


def month_ranges(start: dt.date, end: dt.date):
    cur = start.replace(day=1)
    while cur <= end:
        nxt = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield cur, min(nxt - dt.timedelta(days=1), end)
        cur = nxt


def sync_masters(cfg, company):
    ledgers, stock = fetch_ledgers(cfg, company), fetch_stock_items(cfg, company)
    api(cfg, "POST", "/v1/ingest/masters", {"company": company, "ledgers": ledgers, "stock_items": stock})
    log.info("[%s] masters: %d ledgers, %d stock items", company, len(ledgers), len(stock))


def initial_voucher_sync(cfg, state, company):
    cs = state.setdefault(company, {"max_alter_id": 0, "initial_done": False, "resume_from": cfg["since"]})
    for m_start, m_end in month_ranges(dt.date.fromisoformat(cs["resume_from"]), dt.date.today()):
        if STOP.is_set() or PAUSED.is_set():
            return
        set_status(f"[{company}] first sync: {m_start:%b %Y}")
        vouchers = fetch_vouchers(cfg, company, m_start, m_end)
        if cfg.get("tally_mode") == "legacy":
            post_changed(cfg, company, vouchers, save=False)
        else:
            post_vouchers(cfg, company, vouchers)
        if vouchers:
            cs["max_alter_id"] = max(cs["max_alter_id"], max(v["alter_id"] for v in vouchers))
        cs["resume_from"] = m_start.isoformat()
        save_state(state)
        log.info("[%s] %s: %d vouchers", company, m_start.strftime("%b %Y"), len(vouchers))
        STOP.wait(1)                                    # let Tally breathe between chunks
    if cfg.get("tally_mode") == "legacy":
        save_hashes()
    cs["initial_done"] = True
    cs["deep_alter"] = cs["max_alter_id"]
    cs["last_reconcile"] = time.time()
    save_state(state)


def incremental_voucher_sync(cfg, state, company):
    cs = state[company]
    vouchers = fetch_vouchers(cfg, company, dt.date.fromisoformat(cfg["since"]),
                              dt.date.today() + dt.timedelta(days=365), min_alter_id=cs["max_alter_id"])
    if vouchers:
        post_vouchers(cfg, company, vouchers)
        cs["max_alter_id"] = max(v["alter_id"] for v in vouchers)
        save_state(state)
        log.info("[%s] incremental: %d changed vouchers (max AlterID %d)", company, len(vouchers), cs["max_alter_id"])


def reconcile(cfg, state, company):
    since, until = dt.date.fromisoformat(cfg["since"]), dt.date.today() + dt.timedelta(days=365)
    guids = []
    for m_start, m_end in month_ranges(since, until):
        guids += fetch_voucher_guids(cfg, company, m_start, m_end)
    if guids:
        res = api(cfg, "POST", "/v1/ingest/reconcile",
                  {"company": company, "from_date": since.isoformat(), "to_date": until.isoformat(), "guids": guids})
        log.info("[%s] reconcile: %s", company, res)
    state[company]["last_reconcile"] = time.time()
    save_state(state)


def legacy_incremental(cfg, state, company):
    """Older Tally: re-read the last ~3 months every cycle (and do a full check of all months once a
    day). ALTERID may be missing there, so a fingerprint of each voucher decides what changed, and
    only vouchers whose content changed are uploaded."""
    cs = state[company]
    if time.time() - cs.get("last_reconcile", 0) > 86400:
        return legacy_deep_scan(cfg, state, company)
    today = dt.date.today()
    since = max(dt.date.fromisoformat(cfg["since"]), (today.replace(day=1) - dt.timedelta(days=62)).replace(day=1))
    recent = []
    for m_start, m_end in month_ranges(since, today + dt.timedelta(days=31)):
        recent += fetch_vouchers(cfg, company, m_start, m_end)
    sent = post_changed(cfg, company, recent)
    if sent:
        cs["max_alter_id"] = max(cs["max_alter_id"], max(v["alter_id"] for v in recent))
        save_state(state)
        log.info("[%s] recent months: %d changed vouchers", company, sent)


def legacy_deep_scan(cfg, state, company):
    cs = state[company]
    since = dt.date.fromisoformat(cfg["since"])
    until = dt.date.today() + dt.timedelta(days=31)
    top, guids, sent_total = cs.get("deep_alter", 0), [], 0
    for m_start, m_end in month_ranges(since, until):
        if STOP.is_set() or PAUSED.is_set():
            return
        set_status(f"[{company}] daily full check: {m_start:%b %Y}")
        vs = fetch_vouchers(cfg, company, m_start, m_end)
        guids += [v["guid"] for v in vs]
        # Fingerprints decide what changed, so this also works when ALTERID is missing.
        sent_total += post_changed(cfg, company, vs, save=False)
        if vs:
            top = max(top, max(v["alter_id"] for v in vs))
        STOP.wait(1)
    cs["deep_alter"] = top
    cs["max_alter_id"] = max(cs["max_alter_id"], top)
    if guids:                                              # forget fingerprints of vouchers deleted in Tally
        seen, alive = _hashes().setdefault(company, {}), set(guids)
        for g in [g for g in seen if g not in alive]:
            del seen[g]
    save_hashes()
    if guids:
        res = api(cfg, "POST", "/v1/ingest/reconcile",
                  {"company": company, "from_date": since.isoformat(), "to_date": until.isoformat(), "guids": guids})
        log.info("[%s] daily full check: %d changed vouchers uploaded, %s", company, sent_total, res)
    cs["last_reconcile"] = time.time()
    save_state(state)


def cycle(cfg, state, last_masters):
    discovered = list_companies(cfg)                                  # raises TallyError if unreachable
    if not discovered:
        set_status("Tally is running, but no company is open (or it could not be read).")
        return
    api(cfg, "POST", "/v1/agent/companies", {"companies": discovered})
    enabled = set(api(cfg, "GET", "/v1/agent/settings")["enabled_companies"])
    targets = [c for c in discovered if c in enabled]
    if not targets:
        set_status("Connected. Waiting for you to choose companies on the dashboard.")
        return
    for company in targets:
        if STOP.is_set() or PAUSED.is_set():
            return
        try:
            if time.time() - last_masters.get(company, 0) > 3600:
                sync_masters(cfg, company)
                last_masters[company] = time.time()
            cs = state.get(company)
            if not cs or not cs["initial_done"]:
                initial_voucher_sync(cfg, state, company)
            elif cfg.get("tally_mode") == "legacy":
                legacy_incremental(cfg, state, company)
            else:
                incremental_voucher_sync(cfg, state, company)
                if time.time() - cs.get("last_reconcile", 0) > 86400:
                    reconcile(cfg, state, company)
        except (TallyError, ApiError, ET.ParseError) as e:
            log.error("[%s] %s: %s", company, type(e).__name__, e)
    set_status(f"Last sync OK at {dt.datetime.now():%H:%M}")


TALLY_HELP = ("Cannot reach Tally.\n\nTallyPrime: press F1 (Help) > Settings > Connectivity > "
              "Client/Server configuration, set it to 'Server' or 'Both', port 9000.\n"
              "Tally.ERP 9: press F12 (Configure) > Advanced Configuration, set 'Tally.ERP 9 is acting as' "
              "to 'Both', port 9000.\n\nThen make sure a company is open.")


def worker(cfg, once=False):
    if not cfg["api_url"]:
        notify("Tally Sync", "No server address configured (api_url).")
        return
    cfg["token"] = load_token()
    if not cfg["token"]:
        try:
            if not pair(cfg):
                notify("Tally Sync", "This agent was not connected. Restart it to try again.")
                return
        except (urllib.error.URLError, OSError, ApiError) as e:
            notify("Tally Sync", f"Could not reach the server: {e}")
            return
    state, last_masters, warned = load_state(), {}, False
    while not STOP.is_set():
        if PAUSED.is_set():
            set_status("Paused")
        else:
            try:
                cycle(cfg, state, last_masters)
                warned = False
            except Unauthorized:
                clear_token()
                notify("Tally Sync", "Access was revoked on the website. The agent has stopped.")
                set_status("Disconnected (revoked).")
                STOP.set()
                return
            except TallyError as e:
                set_status("Cannot reach Tally. Is it open with port 9000 enabled?")
                log.warning("Tally error: %s", e)
                if not warned:
                    notify("Tally Sync", TALLY_HELP)
                    warned = True
            except (ApiError, ET.ParseError, urllib.error.URLError, OSError) as e:
                log.error("%s: %s", type(e).__name__, e)
        if once:
            return
        STOP.wait(cfg["poll_seconds"] if not PAUSED.is_set() else 5)


# ---------------------------------------------------------------- tray + main
def run_tray(cfg, thread):
    import pystray
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (64, 64), "#1F3A5F")
    ImageDraw.Draw(img).rectangle((16, 16, 48, 48), fill="white")

    def toggle(icon, item):
        PAUSED.clear() if PAUSED.is_set() else PAUSED.set()

    def quit_(icon, item):
        STOP.set()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda i: STATUS[:60], None, enabled=False),
        pystray.MenuItem("Open dashboard", lambda i, m: webbrowser.open(cfg["api_url"] + "/dashboard")),
        pystray.MenuItem(lambda i: "Resume syncing" if PAUSED.is_set() else "Pause syncing", toggle),
        pystray.MenuItem("Quit", quit_))
    pystray.Icon("tallysync", img, "Tally Sync", menu).run()


def single_instance():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 47653))
    except OSError:
        return None
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-tray", action="store_true")
    args = ap.parse_args()
    lock = single_instance()
    if lock is None:
        print("Agent already running.")
        return
    cfg = load_config()
    log.info("Tally Sync Agent %s starting. Data dir: %s", VERSION, DATA_DIR)
    if args.once:
        worker(cfg, once=True)
        return
    t = threading.Thread(target=worker, args=(cfg,), daemon=True)
    t.start()
    if not args.no_tray:
        try:
            run_tray(cfg, t)
            return
        except ImportError:
            log.info("pystray/Pillow not installed: running without tray icon")
    try:
        while t.is_alive():
            t.join(1)
    except KeyboardInterrupt:
        STOP.set()


if __name__ == "__main__":
    main()