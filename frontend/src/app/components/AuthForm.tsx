"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function AuthForm({ signup }: { signup: boolean }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(""); setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      const result = await api<{ redirect: string }>(signup ? "/auth/signup" : "/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: form.get("email"),
          password: form.get("password"),
          business: form.get("business") || "",
        }),
      });
      router.push(result.redirect || "/dashboard");
      router.refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to continue"); } finally { setBusy(false); }
  }
  return <form className="form" onSubmit={submit}>
    {error && <p className="error">{error}</p>}
    {signup && <><label htmlFor="business">Business name</label><input id="business" name="business" required /></>}
    <label htmlFor="email">Email</label><input id="email" name="email" type="email" required />
    <label htmlFor="password">Password{signup && " (min 8 characters)"}</label><input id="password" name="password" type="password" minLength={signup ? 8 : undefined} required />
    <button disabled={busy}>{busy ? "Please wait..." : signup ? "Create account" : "Log in"}</button>
  </form>;
}
