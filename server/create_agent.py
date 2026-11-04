"""Dev helper (skips the pairing flow): creates merchant + agent + enabled companies, prints a token.
Usage: DATABASE_URL=... python create_agent.py "Sharma Electronics" "Demo Traders"
"""
import hashlib, os, secrets, sys
import psycopg

name = sys.argv[1] if len(sys.argv) > 1 else "Demo Merchant"
companies = sys.argv[2:] or ["Demo Traders"]
token = secrets.token_urlsafe(32)
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    mid = conn.execute("insert into merchants (name) values (%s) returning id", (name,)).fetchone()[0]
    aid = conn.execute("insert into agents (merchant_id, token_hash, label) values (%s,%s,'dev agent') returning id",
                       (mid, hashlib.sha256(token.encode()).hexdigest())).fetchone()[0]
    for c in companies:
        conn.execute("insert into agent_companies (agent_id, name, enabled) values (%s,%s,true)", (aid, c))
print("Agent token (shown once):", token)
