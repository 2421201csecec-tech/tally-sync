"""Merchant-facing website: signup/login, dashboard, device pairing approval, installer download."""
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from common import (check_csrf, check_pw, csrf_token, esc, hash_pw, layout, pool, safe_next)

router = APIRouter()
DOWNLOADS = Path(os.getenv("DOWNLOADS_DIR", Path(__file__).parent / "downloads"))
INSTALLER = "TallySyncSetup.exe"


def page(request: Request, title: str, body: str, status: int = 200) -> HTMLResponse:
    logged = bool(request.session.get("mid"))
    html = layout(title, body, logged).replace("__CSRF__", csrf_token(request))
    return HTMLResponse(html, status_code=status)


def csrf_field(request) -> str:
    return f'<input type="hidden" name="csrf" value="{esc(csrf_token(request))}">'


def require_login(request: Request):
    if not request.session.get("mid"):
        return RedirectResponse("/login?next=" + quote(str(request.url.path) +
                                ("?" + request.url.query if request.url.query else "")), 303)
    return None


# ------------------------------------------------------------------ home / auth
@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    if request.session.get("mid"):
        return RedirectResponse("/dashboard", 303)
    return page(request, "Tally Sync", """<div class="card"><h1>Connect Tally to the cloud</h1>
      <p>Install a small agent on the PC where Tally runs. After you approve it here, it securely syncs
      your ledgers, stock and vouchers. You choose which companies, and you can revoke access any time.</p>
      <a class="btn" href="/signup">Create account</a> <a class="btn alt" href="/login">Log in</a></div>""")


def auth_form(request, kind, error="", nxt=""):
    signup = kind == "signup"
    extra = '<label>Business name</label><input type="text" name="business" required>' if signup else ""
    err = f'<p class="err">{esc(error)}</p>' if error else ""
    return page(request, "Sign up" if signup else "Log in", f"""<div class="card" style="max-width:420px">
      <h2>{'Create your account' if signup else 'Log in'}</h2>{err}
      <form method="post">{csrf_field(request)}<input type="hidden" name="next" value="{esc(nxt)}">
      {extra}<label>Email</label><input type="email" name="email" required>
      <label>Password{' (min 8 characters)' if signup else ''}</label><input type="password" name="password" required>
      <button>{'Sign up' if signup else 'Log in'}</button></form></div>""")


@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request, next: str = ""):
    return auth_form(request, "signup", nxt=next)


@router.post("/signup")
def signup(request: Request, business: str = Form(...), email: str = Form(...),
           password: str = Form(...), csrf: str = Form(""), next: str = Form("")):
    check_csrf(request, csrf)
    email = email.strip().lower()
    if len(password) < 8:
        return auth_form(request, "signup", "Password must be at least 8 characters.", next)
    with pool.connection() as conn:
        if conn.execute("select 1 from users where email=%s", (email,)).fetchone():
            return auth_form(request, "signup", "That email is already registered.", next)
        mid = conn.execute("insert into merchants(name) values (%s) returning id",
                           (business.strip()[:120],)).fetchone()[0]
        uid = conn.execute("insert into users(merchant_id,email,password_hash) values (%s,%s,%s) returning id",
                           (mid, email, hash_pw(password))).fetchone()[0]
    request.session.clear()
    request.session.update(mid=str(mid), uid=str(uid))
    return RedirectResponse(safe_next(next), 303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = ""):
    return auth_form(request, "login", nxt=next)


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...),
          csrf: str = Form(""), next: str = Form("")):
    check_csrf(request, csrf)
    with pool.connection() as conn:
        row = conn.execute("select id, merchant_id, password_hash from users where email=%s",
                           (email.strip().lower(),)).fetchone()
    if not row or not check_pw(password, row[2]):
        return auth_form(request, "login", "Wrong email or password.", next)
    request.session.clear()
    request.session.update(mid=str(row[1]), uid=str(row[0]))
    return RedirectResponse(safe_next(next), 303)


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/", 303)


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if (r := require_login(request)):
        return r
    mid = request.session["mid"]
    with pool.connection() as conn:
        name = conn.execute("select name from merchants where id=%s", (mid,)).fetchone()[0]
        agents = conn.execute(
            """select id, hostname, version, last_seen, now() - last_seen < interval '15 minutes'
               from agents where merchant_id=%s and revoked_at is null order by created_at""", (mid,)).fetchall()
        stats = conn.execute(
            """select c.name,
                 (select count(*) from vouchers v where v.company_id=c.id and not v.is_deleted),
                 (select count(*) from ledgers l where l.company_id=c.id),
                 (select count(*) from stock_items s where s.company_id=c.id)
               from companies c where c.merchant_id=%s order by c.name""", (mid,)).fetchall()
        agent_blocks = ""
        for aid, host, ver, seen, online in agents:
            comps = conn.execute("select name, enabled from agent_companies where agent_id=%s order by name",
                                 (aid,)).fetchall()
            if comps:
                boxes = "".join(f'<label style="display:block;margin:4px 0"><input type="checkbox" name="enabled" '
                                f'value="{esc(n)}" {"checked" if en else ""}> {esc(n)}</label>' for n, en in comps)
                form = (f'<form method="post" action="/agents/{aid}/companies">{csrf_field(request)}'
                        f'<p class="muted">Tick the Tally companies this agent may sync:</p>{boxes}'
                        f'<button>Save choice</button></form>')
            else:
                form = '<p class="muted">Waiting for the agent to report its Tally companies...</p>'
            status = '<span class="ok">Online</span>' if online else '<span class="warn">Not seen recently</span>'
            seen_txt = seen.strftime("%d %b %Y %H:%M UTC") if seen else "never"
            agent_blocks += (f'<div class="card"><h2>Agent on {esc(host or "unknown PC")} {status}</h2>'
                             f'<p class="muted">Last contact: {seen_txt} &middot; version {esc(ver or "?")}</p>{form}'
                             f'<form method="post" action="/agents/{aid}/revoke" style="margin-top:12px" '
                             f'onsubmit="return confirm(\'Disconnect this agent? It will stop syncing.\')">'
                             f'{csrf_field(request)}<button class="danger">Revoke access</button></form></div>')
    stat_rows = "".join(f"<tr><td>{esc(n)}</td><td>{v}</td><td>{l}</td><td>{s}</td></tr>" for n, v, l, s in stats)
    stat_html = (f'<div class="card"><h2>Synced data</h2><table><tr><th>Company</th><th>Vouchers</th>'
                 f'<th>Ledgers</th><th>Stock items</th></tr>{stat_rows}</table></div>') if stats else ""
    installer_ready = (DOWNLOADS / INSTALLER).exists()
    dl = (f'<a class="btn" href="/download/{INSTALLER}">Download agent for Windows</a>' if installer_ready
          else '<p class="warn">The installer has not been uploaded to this server yet.</p>')
    body = f"""<h1>{esc(name)}</h1>
      <div class="card"><h2>1. Install the agent</h2>
        <p>Run it on the Windows PC where Tally ERP 9 or TallyPrime is open. It will open this website to ask your permission.</p>{dl}
        <p class="muted">Agent shows a code but no page opened? Enter it here:</p>
        <form method="get" action="/pair"><input type="text" name="code" placeholder="ABCD-2345" style="max-width:200px">
        <button class="alt">Continue</button></form></div>
      {agent_blocks or '<div class="card"><h2>2. Connected agents</h2><p class="muted">None yet.</p></div>'}
      {stat_html}"""
    return page(request, "Dashboard", body)


@router.post("/agents/{agent_id}/companies")
async def save_companies(agent_id: str, request: Request):
    if (r := require_login(request)):
        return r
    form = await request.form()
    check_csrf(request, str(form.get("csrf", "")))
    chosen = [str(v) for v in form.getlist("enabled")]
    with pool.connection() as conn:
        if not conn.execute("select 1 from agents where id=%s and merchant_id=%s and revoked_at is null",
                            (agent_id, request.session["mid"])).fetchone():
            raise HTTPException(404)
        conn.execute("update agent_companies set enabled = (name = any(%s)) where agent_id=%s",
                     (chosen, agent_id))
    return RedirectResponse("/dashboard", 303)


@router.post("/agents/{agent_id}/revoke")
def revoke(agent_id: str, request: Request, csrf: str = Form("")):
    if (r := require_login(request)):
        return r
    check_csrf(request, csrf)
    with pool.connection() as conn:
        conn.execute("update agents set revoked_at=now() where id=%s and merchant_id=%s",
                     (agent_id, request.session["mid"]))
    return RedirectResponse("/dashboard", 303)


# ------------------------------------------------------------------ pairing approval
@router.get("/pair", response_class=HTMLResponse)
def pair_page(request: Request, code: str = ""):
    if (r := require_login(request)):
        return r
    code = code.strip().upper()
    if not code:
        return page(request, "Connect agent", f"""<div class="card"><h2>Connect an agent</h2>
          <form method="get"><input type="text" name="code" placeholder="ABCD-2345"><button>Continue</button></form></div>""")
    with pool.connection() as conn:
        row = conn.execute("""select hostname from pairing_requests
                              where user_code=%s and status='pending' and expires_at > now()""", (code,)).fetchone()
    if not row:
        return page(request, "Connect agent", '<div class="card"><h2>Code not found</h2>'
                    '<p class="err">This code is invalid or has expired. Restart the agent to get a new one.</p></div>', 404)
    return page(request, "Allow agent?", f"""<div class="card"><h2>Allow this agent to connect?</h2>
      <p>An agent on the computer <b>{esc(row[0] or 'unknown')}</b> wants to connect to your account.</p>
      <p>Confirmation code: <span class="code">{esc(code)}</span><br>
      <span class="muted">Only continue if this matches the code shown by the agent.</span></p>
      <p>If you allow it, the agent will be able to <b>read</b> ledgers, stock items and vouchers from
      the Tally companies <b>you choose next</b> on your dashboard. It cannot change anything in Tally.
      You can revoke access at any time.</p>
      <form method="post" action="/pair">{csrf_field(request)}<input type="hidden" name="code" value="{esc(code)}">
      <button name="action" value="allow">Allow</button>
      <button name="action" value="deny" class="alt">Deny</button></form></div>""")


@router.post("/pair", response_class=HTMLResponse)
def pair_decide(request: Request, code: str = Form(...), action: str = Form(...), csrf: str = Form("")):
    if (r := require_login(request)):
        return r
    check_csrf(request, csrf)
    status = "approved" if action == "allow" else "denied"
    with pool.connection() as conn:
        n = conn.execute("""update pairing_requests set status=%s, merchant_id=%s
                            where user_code=%s and status='pending' and expires_at > now()""",
                         (status, request.session["mid"], code.strip().upper())).rowcount
    if not n:
        return page(request, "Connect agent", '<div class="card"><p class="err">Code expired or already used.</p></div>', 400)
    msg = ("Agent approved. Go to your dashboard and choose which Tally companies it may sync."
           if status == "approved" else "Request denied. The agent will not be connected.")
    return page(request, "Done", f'<div class="card"><h2>{esc(msg)}</h2><a class="btn" href="/dashboard">Open dashboard</a></div>')


# ------------------------------------------------------------------ installer download
@router.get("/download/" + INSTALLER)
def download(request: Request):
    if (r := require_login(request)):
        return r
    path = DOWNLOADS / INSTALLER
    if not path.exists():
        raise HTTPException(404, "installer not uploaded yet")
    return FileResponse(path, filename=INSTALLER, media_type="application/octet-stream")
