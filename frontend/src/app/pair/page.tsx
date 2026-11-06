"use client";

import { FormEvent, useEffect, useState } from "react";
import { Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Header from "../components/Header";
import { api } from "@/lib/api";

export default function PairPage() {
  return <Suspense fallback={<><Header /><main className="auth card"><p>Loading...</p></main></>}><PairContent /></Suspense>;
}

function PairContent() {
  const params = useSearchParams();
  const router = useRouter();
  const initialCode = params.get("code")?.toUpperCase() || "";
  const [code, setCode] = useState(initialCode);
  const [hostname, setHostname] = useState("");
  const [csrf, setCsrf] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  useEffect(() => {
    void api<{ csrf: string; authenticated: boolean }>("/auth/me").then((result) => {
      setCsrf(result.authenticated ? result.csrf : "");
      if (!result.authenticated) setError("Please log in first.");
    }).catch(() => setError("Please log in first."));
    if (initialCode) void lookup(initialCode);
  }, [initialCode]);
  async function lookup(value: string) {
    setError("");
    try { const result = await api<{ hostname: string }>(`/pair?code=${encodeURIComponent(value)}`); setHostname(result.hostname); }
    catch (e) { setHostname(""); setError(e instanceof Error ? e.message : "Code not found"); }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hostname) { await lookup(code); return; }
    try {
      const submitter = (event.nativeEvent as SubmitEvent).submitter;
      const action = submitter instanceof HTMLButtonElement ? submitter.value : "allow";
      const result = await api<{ message: string }>("/pair/decision", { method: "POST", body: JSON.stringify({ code, action, csrf }) });
      setDone(result.message);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to decide"); }
  }
  return <><Header authenticated={Boolean(csrf)} csrf={csrf} /><main className="auth card"><h1>{done ? "Done" : hostname ? "Allow this agent?" : "Connect an agent"}</h1>{done ? <><p>{done}</p><button onClick={() => router.push("/dashboard")}>Open dashboard</button></> : <form className="form" onSubmit={submit}>{error && <p className="error">{error}</p>}<label htmlFor="code">Confirmation code</label><input id="code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="ABCD-2345" required />{hostname ? <><p>An agent on <strong>{hostname}</strong> wants to connect to your account.</p><p className="muted">Only continue if this matches the code shown by the agent. The agent can only read the Tally companies you choose next.</p><span className="code">{code}</span><div className="actions"><button name="action" value="allow">Allow</button><button className="secondary" name="action" value="deny">Deny</button></div></> : <button>Continue</button>}</form>}</main></>;
}
