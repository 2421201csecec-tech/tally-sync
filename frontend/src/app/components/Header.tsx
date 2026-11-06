"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function Header({ authenticated = false, csrf = "" }: { authenticated?: boolean; csrf?: string }) {
  const router = useRouter();
  async function logout() {
    await api("/auth/logout", { method: "POST", body: JSON.stringify({ csrf }) });
    router.push("/");
    router.refresh();
  }
  return (
    <header className="topbar">
      <Link className="brand" href="/">TALLY SYNC</Link>
      {authenticated ? <nav className="nav"><Link href="/dashboard">Dashboard</Link><button className="secondary" onClick={logout}>Log out</button></nav> : <nav className="nav"><Link href="/login">Log in</Link><Link href="/signup">Sign up</Link></nav>}
    </header>
  );
}
