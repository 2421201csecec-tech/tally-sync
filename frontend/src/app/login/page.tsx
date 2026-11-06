import Link from "next/link";
import Header from "../components/Header";
import AuthForm from "../components/AuthForm";

export default function LoginPage() {
  return <><Header /><main className="auth card"><h1>Log in</h1><AuthForm signup={false} /><p className="muted">New to Tally Sync? <Link href="/signup">Create an account</Link>.</p></main></>;
}
