"""Tally Sync server: agent ingestion API + device pairing + merchant website.
Run: uvicorn main:app --host 0.0.0.0 --port 8000
"""
import os
import secrets
from datetime import timedelta

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
import merchant_api
from common import agent_auth, pool, require_enabled, sha256
import web

app = FastAPI(title="Tally Sync API")
app.add_middleware(SessionMiddleware, secret_key=os.environ["SECRET_KEY"],
                   https_only=os.getenv("HTTPS_ONLY", "0") == "1",
                   same_site="lax", max_age=14 * 86400)


app.include_router(web.router)
app.include_router(merchant_api.router, prefix="/api")

PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no look-alike characters
PAIR_TTL_MIN = 10


def company_id(conn, merchant_id, name):
    return conn.execute(
        "insert into companies (merchant_id, name) values (%s, %s) "
        "on conflict (merchant_id, name) do update set name = excluded.name returning id",
        (merchant_id, name)).fetchone()[0]


@app.get("/health")
def health():
    return {"ok": True}


# ------------------------------------------------------------------ device pairing (agent side)
class PairStart(BaseModel):
    hostname: str = ""
    version: str = ""


class PairPoll(BaseModel):
    device_code: str


@app.post("/v1/pair/start")
def pair_start(body: PairStart, request: Request):
    device_code = secrets.token_urlsafe(32)
    for _ in range(10):
        raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        user_code = raw[:4] + "-" + raw[4:]
        try:
            with pool.connection() as conn:
                conn.execute(
                    """insert into pairing_requests (device_code_hash, user_code, hostname, expires_at)
                       values (%s,%s,%s, now() + %s)""",
                    (sha256(device_code), user_code, body.hostname[:100], timedelta(minutes=PAIR_TTL_MIN)))
            break
        except psycopg.errors.UniqueViolation:
            continue
    else:
        raise HTTPException(500, "could not allocate code")
    base = PUBLIC_URL or str(request.base_url).rstrip("/")
    return {"device_code": device_code, "user_code": user_code,
            "verification_url": f"{base}/pair?code={user_code}",
            "expires_in": PAIR_TTL_MIN * 60, "interval": 3}


@app.post("/v1/pair/poll")
def pair_poll(body: PairPoll):
    with pool.connection() as conn:
        row = conn.execute(
            """select id, status, merchant_id, hostname, expires_at < now()
               from pairing_requests where device_code_hash=%s""", (sha256(body.device_code),)).fetchone()
        if not row:
            return {"status": "invalid"}
        pid, status, merchant_id, hostname, expired = row
        if status == "pending":
            return {"status": "expired" if expired else "pending"}
        if status != "approved":
            return {"status": status}               # denied | consumed
        # approved: hand out the token exactly once
        claimed = conn.execute("update pairing_requests set status='consumed' where id=%s and status='approved' returning id",
                               (pid,)).fetchone()
        if not claimed:
            return {"status": "consumed"}
        token = secrets.token_urlsafe(32)
        agent_id = conn.execute(
            "insert into agents (merchant_id, token_hash, hostname, label) values (%s,%s,%s,%s) returning id",
            (merchant_id, sha256(token), hostname, hostname)).fetchone()[0]
        conn.execute("update pairing_requests set agent_id=%s where id=%s", (agent_id, pid))
    return {"status": "approved", "token": token}


# ------------------------------------------------------------------ agent settings
class CompaniesIn(BaseModel):
    companies: list[str]


@app.post("/v1/agent/companies")
def agent_companies(body: CompaniesIn, who=Depends(agent_auth)):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.executemany("insert into agent_companies (agent_id, name) values (%s,%s) on conflict do nothing",
                            [(who["agent_id"], n) for n in body.companies if n])
    return {"ok": True}


@app.get("/v1/agent/settings")
def agent_settings(who=Depends(agent_auth)):
    with pool.connection() as conn:
        rows = conn.execute("select name from agent_companies where agent_id=%s and enabled order by name",
                            (who["agent_id"],)).fetchall()
    return {"enabled_companies": [r[0] for r in rows]}


# ------------------------------------------------------------------ ingestion
class MastersIn(BaseModel):
    company: str
    ledgers: list[dict] = []
    stock_items: list[dict] = []


class VouchersIn(BaseModel):
    company: str
    batch_id: str
    max_alter_id: int
    vouchers: list[dict]


class ReconcileIn(BaseModel):
    company: str
    from_date: str
    to_date: str
    guids: list[str]


@app.post("/v1/ingest/masters")
def ingest_masters(body: MastersIn, who=Depends(agent_auth)):
    with pool.connection() as conn:
        require_enabled(conn, who["agent_id"], body.company)
        cid = company_id(conn, who["merchant_id"], body.company)
        with conn.cursor() as cur:
            cur.executemany(
                """insert into ledgers (company_id, guid, name, parent, opening_balance, closing_balance, alter_id)
                   values (%s,%s,%s,%s,%s,%s,%s)
                   on conflict (company_id, guid) do update set
                     name=excluded.name, parent=excluded.parent, opening_balance=excluded.opening_balance,
                     closing_balance=excluded.closing_balance, alter_id=excluded.alter_id, updated_at=now()""",
                [(cid, l["guid"], l["name"], l.get("parent"), l.get("opening_balance"),
                  l.get("closing_balance"), l.get("alter_id")) for l in body.ledgers])
            cur.executemany(
                """insert into stock_items (company_id, guid, name, parent, unit, closing_qty, closing_value, alter_id)
                   values (%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (company_id, guid) do update set
                     name=excluded.name, parent=excluded.parent, unit=excluded.unit,
                     closing_qty=excluded.closing_qty, closing_value=excluded.closing_value,
                     alter_id=excluded.alter_id, updated_at=now()""",
                [(cid, s["guid"], s["name"], s.get("parent"), s.get("unit"), s.get("closing_qty"),
                  s.get("closing_value"), s.get("alter_id")) for s in body.stock_items])
    return {"ledgers": len(body.ledgers), "stock_items": len(body.stock_items)}


@app.post("/v1/ingest/vouchers")
def ingest_vouchers(body: VouchersIn, who=Depends(agent_auth)):
    with pool.connection() as conn:
        require_enabled(conn, who["agent_id"], body.company)
        cid = company_id(conn, who["merchant_id"], body.company)
        with conn.cursor() as cur:
            cur.executemany(
                """insert into vouchers (company_id, guid, alter_id, date, voucher_type, voucher_number,
                       party, narration, amount, ledger_entries, inventory_entries, raw)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (company_id, guid) do update set
                     alter_id=excluded.alter_id, date=excluded.date, voucher_type=excluded.voucher_type,
                     voucher_number=excluded.voucher_number, party=excluded.party, narration=excluded.narration,
                     amount=excluded.amount, ledger_entries=excluded.ledger_entries,
                     inventory_entries=excluded.inventory_entries, raw=excluded.raw,
                     is_deleted=false, updated_at=now()""",
                [(cid, v["guid"], v["alter_id"], v.get("date"), v.get("type"), v.get("number"),
                  v.get("party"), v.get("narration"), v.get("amount"),
                  Jsonb(v.get("ledger_entries", [])), Jsonb(v.get("inventory_entries", [])), v.get("raw"))
                 for v in body.vouchers])
    return {"received": len(body.vouchers), "batch_id": body.batch_id}


@app.post("/v1/ingest/reconcile")
def reconcile(body: ReconcileIn, who=Depends(agent_auth)):
    if not body.guids:
        raise HTTPException(400, "empty GUID list refused (would mark everything deleted)")
    with pool.connection() as conn:
        require_enabled(conn, who["agent_id"], body.company)
        cid = company_id(conn, who["merchant_id"], body.company)
        deleted = conn.execute(
            """update vouchers set is_deleted = true, updated_at = now()
               where company_id = %s and date between %s and %s and not is_deleted and guid <> all(%s)""",
            (cid, body.from_date, body.to_date, body.guids)).rowcount
    return {"marked_deleted": deleted}
