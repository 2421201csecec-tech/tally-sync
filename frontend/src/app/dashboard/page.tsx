"use client";

import { useEffect, useState } from "react";
import Header from "../components/Header";
import { api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  async function load() {
    try { setData(await api<Dashboard>("/dashboard")); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to load dashboard"); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    void api<Dashboard>("/dashboard").then(setData).catch((e: unknown) => {
      setError(e instanceof Error ? e.message : "Unable to load dashboard");
    }).finally(() => setLoading(false));
  }, []);
  if (loading) return <><Header /><main className="shell"><p>Loading dashboard...</p></main></>;
  if (error || !data) return <><Header /><main className="shell"><p className="error">{error || "Not authenticated"}</p></main></>;
  return <><Header authenticated csrf={data.csrf} /><main className="shell dashboard-grid">
    <div><p className="eyebrow">DASHBOARD</p><h1>{data.merchant_name}</h1></div>
    <section className="card"><div className="card-header"><div><h2>Install the agent</h2><p className="muted">Run it on the Windows PC where TallyPrime is open.</p></div>{data.installer_ready ? <a className="button" href="/api/download/installer">Download for Windows</a> : <span className="muted">Installer unavailable</span>}</div><p className="muted">After installation, approve the connection here and choose which companies it may sync.</p><a className="button secondary" href="/pair">Connect an agent</a></section>
    {data.agents.length ? data.agents.map((agent) => <AgentCard key={agent.id} agent={agent} csrf={data.csrf} onChange={load} />) : <section className="card"><h2>Connected agents</h2><p className="muted">None yet. Install the agent to get started.</p></section>}
    {data.companies.length > 0 && <section className="card"><h2>Synced data</h2><table><thead><tr><th>Company</th><th>Vouchers</th><th>Ledgers</th><th>Stock items</th></tr></thead><tbody>{data.companies.map((company) => <tr key={company.name}><td>{company.name}</td><td>{company.vouchers}</td><td>{company.ledgers}</td><td>{company.stock_items}</td></tr>)}</tbody></table></section>}
  </main></>;
}

function AgentCard({ agent, csrf, onChange }: { agent: Dashboard["agents"][number]; csrf: string; onChange: () => void }) {
  const [enabled, setEnabled] = useState(agent.companies.filter((c) => c.enabled).map((c) => c.name));
  const [message, setMessage] = useState("");
  async function save() {
    await api(`/agents/${agent.id}/companies`, { method: "POST", body: JSON.stringify({ csrf, enabled }) });
    setMessage("Saved"); onChange();
  }
  async function revoke() {
    if (!window.confirm("Disconnect this agent? It will stop syncing.")) return;
    await api(`/agents/${agent.id}/revoke`, { method: "POST", body: JSON.stringify({ csrf }) });
    onChange();
  }
  function toggle(name: string) { setEnabled((current) => current.includes(name) ? current.filter((item) => item !== name) : [...current, name]); }
  return <section className="card"><div className="agent-header"><div><h2>Agent on {agent.hostname || "unknown PC"}</h2><p className="muted">Last contact: {agent.last_seen ? new Date(agent.last_seen).toLocaleString() : "never"} · version {agent.version || "?"}</p></div><span className={agent.online ? "status-online" : "status-offline"}>{agent.online ? "Online" : "Not seen recently"}</span></div>{agent.companies.length ? <><p className="muted">Choose the Tally companies this agent may sync:</p><div className="company-list">{agent.companies.map((company) => <label key={company.name}><input type="checkbox" checked={enabled.includes(company.name)} onChange={() => toggle(company.name)} /> {company.name}</label>)}</div><div className="row-actions"><button onClick={save}>Save choice</button>{message && <span className="muted">{message}</span>}<button className="danger" onClick={revoke}>Revoke access</button></div></> : <p className="muted">Waiting for the agent to report its Tally companies...</p>}</section>;
}
