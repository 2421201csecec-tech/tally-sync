from pathlib import Path
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from common import check_csrf, check_pw, csrf_token, hash_pw, pool, safe_next

router = APIRouter()
DOWNLOADS = Path(os.getenv("DOWNLOADS_DIR", Path(__file__).parent / "downloads"))
INSTALLER = "TallySyncSetup.exe"
INSTALLER_URL = os.getenv("INSTALLER_URL", "").strip()


class Credentials(BaseModel):
    email: str
    password: str
    business: str = ""
    next: str = ""


class CompanySelection(BaseModel):
    csrf: str = ""
    enabled: list[str] = Field(default_factory=list)


class PairDecision(BaseModel):
    code: str
    action: str
    csrf: str = ""


def require_merchant(request: Request) -> str:
    mid = request.session.get("mid")
    if not mid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(mid)


def json_session(request: Request) -> dict:
    return {"authenticated": bool(request.session.get("mid")), "csrf": csrf_token(request)}


@router.get("/auth/me")
def auth_me(request: Request):
    return json_session(request)


@router.post("/auth/signup")
def signup(body: Credentials, request: Request):
    email = body.email.strip().lower()
    business = body.business.strip()[:120]
    if not business:
        raise HTTPException(422, "Business name is required")
    if len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")
    with pool.connection() as conn:
        if conn.execute("select 1 from users where email=%s", (email,)).fetchone():
            raise HTTPException(409, "That email is already registered")
        mid = conn.execute(
            "insert into merchants(name) values (%s) returning id", (business,)
        ).fetchone()[0]
        uid = conn.execute(
            "insert into users(merchant_id,email,password_hash) values (%s,%s,%s) returning id",
            (mid, email, hash_pw(body.password)),
        ).fetchone()[0]
    request.session.clear()
    request.session.update(mid=str(mid), uid=str(uid))
    return {"ok": True, "redirect": safe_next(body.next), **json_session(request)}


@router.post("/auth/login")
def login(body: Credentials, request: Request):
    with pool.connection() as conn:
        row = conn.execute(
            "select id, merchant_id, password_hash from users where email=%s",
            (body.email.strip().lower(),),
        ).fetchone()
    if not row or not check_pw(body.password, row[2]):
        raise HTTPException(401, "Wrong email or password")
    request.session.clear()
    request.session.update(mid=str(row[1]), uid=str(row[0]))
    return {"ok": True, "redirect": safe_next(body.next), **json_session(request)}


@router.post("/auth/logout")
def logout(request: Request, body: CompanySelection | None = None):
    check_csrf(request, body.csrf if body else "")
    request.session.clear()
    return {"ok": True}


@router.get("/dashboard")
def get_dashboard(request: Request):
    mid = require_merchant(request)
    with pool.connection() as conn:
        merchant = conn.execute("SELECT name FROM merchants WHERE id = %s", (mid,)).fetchone()
        if not merchant:
            raise HTTPException(status_code=404, detail="Merchant not found")
        agents = conn.execute(
            """
            SELECT id, hostname, version, last_seen,
                   now() - last_seen < interval '15 minutes' AS online
            FROM agents
            WHERE merchant_id = %s AND revoked_at IS NULL
            ORDER BY created_at
            """,
            (mid,),
        ).fetchall()
        companies = conn.execute(
            """
            SELECT c.name,
                   (SELECT count(*) FROM vouchers v
                    WHERE v.company_id = c.id AND NOT v.is_deleted),
                   (SELECT count(*) FROM ledgers l WHERE l.company_id = c.id),
                   (SELECT count(*) FROM stock_items s WHERE s.company_id = c.id)
            FROM companies c WHERE c.merchant_id = %s ORDER BY c.name
            """,
            (mid,),
        ).fetchall()
        agent_data = []
        for agent_id, hostname, version, last_seen, online in agents:
            permissions = conn.execute(
                "SELECT name, enabled FROM agent_companies WHERE agent_id=%s ORDER BY name",
                (agent_id,),
            ).fetchall()
            agent_data.append(
                {
                    "id": str(agent_id),
                    "hostname": hostname,
                    "version": version,
                    "last_seen": last_seen.isoformat() if last_seen else None,
                    "online": bool(online),
                    "companies": [{"name": name, "enabled": enabled} for name, enabled in permissions],
                }
            )
    installer_ready = (DOWNLOADS / INSTALLER).exists() or bool(INSTALLER_URL)
    return {
        "merchant_name": merchant[0],
        "installer_ready": installer_ready,
        "agents": agent_data,
        "companies": [
            {"name": name, "vouchers": vouchers, "ledgers": ledgers, "stock_items": stock_items}
            for name, vouchers, ledgers, stock_items in companies
        ],
        "csrf": csrf_token(request),
    }


@router.post("/agents/{agent_id}/companies")
def save_companies(agent_id: str, body: CompanySelection, request: Request):
    mid = require_merchant(request)
    check_csrf(request, body.csrf)
    with pool.connection() as conn:
        if not conn.execute(
            "select 1 from agents where id=%s and merchant_id=%s and revoked_at is null",
            (agent_id, mid),
        ).fetchone():
            raise HTTPException(404, "Agent not found")
        conn.execute(
            "update agent_companies set enabled = (name = any(%s)) where agent_id=%s",
            (body.enabled, agent_id),
        )
    return {"ok": True}


@router.post("/agents/{agent_id}/revoke")
def revoke_agent(agent_id: str, body: CompanySelection, request: Request):
    mid = require_merchant(request)
    check_csrf(request, body.csrf)
    with pool.connection() as conn:
        conn.execute(
            "update agents set revoked_at=now() where id=%s and merchant_id=%s",
            (agent_id, mid),
        )
    return {"ok": True}


@router.get("/pair")
def pair_details(code: str, request: Request):
    require_merchant(request)
    normalized = code.strip().upper()
    with pool.connection() as conn:
        row = conn.execute(
            """select hostname from pairing_requests
               where user_code=%s and status='pending' and expires_at > now()""",
            (normalized,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "This code is invalid or has expired")
    return {"code": normalized, "hostname": row[0] or "unknown"}


@router.post("/pair/decision")
def pair_decision(body: PairDecision, request: Request):
    mid = require_merchant(request)
    check_csrf(request, body.csrf)
    action = body.action.strip().lower()
    if action not in ("allow", "deny"):
        raise HTTPException(422, "Action must be allow or deny")
    status = "approved" if action == "allow" else "denied"
    with pool.connection() as conn:
        changed = conn.execute(
            """update pairing_requests set status=%s, merchant_id=%s
               where user_code=%s and status='pending' and expires_at > now()""",
            (status, mid, body.code.strip().upper()),
        ).rowcount
    if not changed:
        raise HTTPException(400, "Code expired or already used")
    return {
        "ok": True,
        "message": (
            "Agent approved. Choose which Tally companies it may sync on the dashboard."
            if status == "approved"
            else "Request denied. The agent will not be connected."
        ),
    }


@router.get("/download/installer")
def download_installer(request: Request):
    require_merchant(request)
    path = DOWNLOADS / INSTALLER
    if path.exists():
        return FileResponse(path, filename=INSTALLER, media_type="application/octet-stream")
    if INSTALLER_URL:
        return RedirectResponse(INSTALLER_URL, status_code=307)
    raise HTTPException(404, "Installer not uploaded yet")
