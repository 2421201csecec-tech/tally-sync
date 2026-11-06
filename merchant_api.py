from fastapi import APIRouter, HTTPException, Request

from common import pool

router = APIRouter()


def require_merchant(request: Request):
    mid = request.session.get("mid")

    if not mid:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return mid


@router.get("/dashboard")
def get_dashboard(request: Request):
    mid = require_merchant(request)

    with pool.connection() as conn:
        merchant = conn.execute(
            "SELECT name FROM merchants WHERE id = %s",
            (mid,),
        ).fetchone()

        if not merchant:
            raise HTTPException(status_code=404, detail="Merchant not found")

        agents = conn.execute(
            """
            SELECT
                id,
                hostname,
                version,
                last_seen,
                now() - last_seen < interval '15 minutes' AS online
            FROM agents
            WHERE merchant_id = %s
              AND revoked_at IS NULL
            ORDER BY created_at
            """,
            (mid,),
        ).fetchall()

        companies = conn.execute(
            """
            SELECT
                c.name,
                (SELECT count(*) FROM vouchers v
                 WHERE v.company_id = c.id AND NOT v.is_deleted) AS vouchers,
                (SELECT count(*) FROM ledgers l
                 WHERE l.company_id = c.id) AS ledgers,
                (SELECT count(*) FROM stock_items s
                 WHERE s.company_id = c.id) AS stock_items
            FROM companies c
            WHERE c.merchant_id = %s
            ORDER BY c.name
            """,
            (mid,),
        ).fetchall()

        agent_data = []

        for agent in agents:
            agent_id, hostname, version, last_seen, online = agent

            permissions = conn.execute(
                """
                SELECT name, enabled
                FROM agent_companies
                WHERE agent_id = %s
                ORDER BY name
                """,
                (agent_id,),
            ).fetchall()

            agent_data.append({
                "id": str(agent_id),
                "hostname": hostname,
                "version": version,
                "last_seen": last_seen.isoformat() if last_seen else None,
                "online": online,
                "companies": [
                    {"name": name, "enabled": enabled}
                    for name, enabled in permissions
                ],
            })

    return {
        "merchant_name": merchant[0],
        "agents": agent_data,
        "companies": [
            {
                "name": name,
                "vouchers": vouchers,
                "ledgers": ledgers,
                "stock_items": stock_items,
            }
            for name, vouchers, ledgers, stock_items in companies
        ],
    }