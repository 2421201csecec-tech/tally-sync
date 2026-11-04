"""Shared pieces: DB pool, agent auth, session/CSRF helpers, HTML layout."""
import hashlib 
import hmac
import html
import os
import secrets

from fastapi import Header, HTTPException, Request
from psycopg_pool import ConnectionPool

pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=10, open=True)
esc = html.escape


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def agent_auth(authorization: str = Header(default=""),
               x_agent_version: str = Header(default="")):
    """Authenticates an installed agent by its bearer token. Revoked agents get 401."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing token")
    with pool.connection() as conn:
        row = conn.execute(
            """update agents set last_seen = now(), version = coalesce(nullif(%s,''), version)
               where token_hash = %s and revoked_at is null
               returning id, merchant_id""",
            (x_agent_version, sha256(authorization[7:]))).fetchone()
    if not row:
        raise HTTPException(401, "invalid or revoked token")
    return {"agent_id": row[0], "merchant_id": row[1]}


def require_enabled(conn, agent_id, company: str):
    row = conn.execute("select enabled from agent_companies where agent_id=%s and name=%s",
                       (agent_id, company)).fetchone()
    if not row or not row[0]:
        raise HTTPException(403, "company not enabled by merchant")


# ---- password hashing (stdlib scrypt) ----
def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + ":" + h.hex()


def check_pw(pw: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


# ---- sessions / csrf ----
def csrf_token(request: Request) -> str:
    t = request.session.get("csrf")
    if not t:
        t = secrets.token_urlsafe(16)
        request.session["csrf"] = t
    return t


def check_csrf(request: Request, token: str):
    if not token or not hmac.compare_digest(token, request.session.get("csrf", "")):
        raise HTTPException(403, "bad csrf token")


def safe_next(n: str) -> str:
    return n if n.startswith("/") and not n.startswith("//") else "/dashboard"


CSS = """
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;background:#f4f6fa;color:#1c2733}
header{background:#1F3A5F;color:#fff;padding:12px 24px;display:flex;justify-content:space-between;align-items:center}
header a{color:#fff;margin-left:16px;text-decoration:none}
main{max-width:860px;margin:24px auto;padding:0 16px}
.card{background:#fff;border-radius:10px;padding:18px 22px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
h1{font-size:22px} h2{font-size:17px;margin-top:0}
input[type=text],input[type=email],input[type=password]{width:100%;padding:9px;margin:6px 0 12px;border:1px solid #c5d0dc;border-radius:6px;box-sizing:border-box}
button,.btn{background:#1F3A5F;color:#fff;border:0;padding:9px 16px;border-radius:6px;cursor:pointer;text-decoration:none;display:inline-block;font-size:14px}
button.danger{background:#b3261e} button.alt{background:#6b7a8c}
table{border-collapse:collapse;width:100%} td,th{padding:7px 8px;border-bottom:1px solid #e3e8ef;text-align:left;font-size:14px}
.ok{color:#1b7f3b;font-weight:600}.warn{color:#b26a00;font-weight:600}.err{color:#b3261e}.muted{color:#6b7a8c;font-size:13px}
.code{font-size:28px;letter-spacing:4px;font-family:monospace;background:#eef3f9;padding:8px 14px;border-radius:6px;display:inline-block}
"""


def layout(title: str, body: str, logged_in: bool = False) -> str:
    nav = ('<a href="/dashboard">Dashboard</a><form method="post" action="/logout" style="display:inline">'
           '<input type="hidden" name="csrf" value="__CSRF__"><button class="alt" style="margin-left:16px">Log out</button></form>'
           if logged_in else '<a href="/login">Log in</a><a href="/signup">Sign up</a>')
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>{esc(title)}</title><style>{CSS}</style></head>"
            f"<body><header><b>Tally Sync</b><span>{nav}</span></header><main>{body}</main></body></html>")
